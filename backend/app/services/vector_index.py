import hashlib
import logging
from collections import defaultdict
from datetime import timedelta

from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import DuplicateJobError
from sqlalchemy import and_, func, or_, select, update

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Course, KnowledgeChunk, KnowledgePoint
from app.models.base import utcnow
from app.services import account_index
from app.services.account_models import default_config, fingerprint, profile_for
from app.services.embeddings import EmbeddingClient
from app.services.extraction_queue import QUEUE_NAME, redis_connection
from app.services.knowledge_index import store_embeddings
from app.services.model_api import ModelAPIError

logger = logging.getLogger(__name__)


def configured():
    settings = get_settings()
    return bool(
        settings.embedding_api_key.get_secret_value()
        and settings.embedding_base_url
        and settings.embedding_model
    )


def pending_entries(db, course_id, *, force=False):
    settings = get_settings()
    statement = (
        select(KnowledgePoint.id, KnowledgePoint.version)
        .join(KnowledgeChunk)
        .where(
            KnowledgePoint.course_id == course_id,
            KnowledgeChunk.course_id == course_id,
            KnowledgePoint.status == "active",
            KnowledgeChunk.version == KnowledgePoint.version,
            or_(
                KnowledgeChunk.embedding_status != "ready",
                KnowledgeChunk.embedding.is_(None),
                KnowledgeChunk.embedding_model.is_(None),
                KnowledgeChunk.embedding_model != settings.embedding_model,
                KnowledgeChunk.embedding_dimensions.is_(None),
                KnowledgeChunk.embedding_dimensions != settings.embedding_dimensions,
                KnowledgeChunk.embedding_fingerprint.is_(None),
                KnowledgeChunk.embedding_fingerprint != fingerprint(default_config("embedding")),
            ),
        )
    )
    if not force:
        statement = statement.where(
            or_(
                KnowledgeChunk.embedding_retry_at.is_(None),
                KnowledgeChunk.embedding_retry_at <= utcnow(),
            )
        )
    return [
        (key, version)
        for key, version in db.execute(statement.distinct().order_by(KnowledgePoint.id))
    ]


def enqueue_index(entries):
    if not entries:
        return False
    with SessionLocal() as db:
        entries, success = account_index.dispatch_entries(db, entries)
    if not entries:
        return success
    if not configured():
        return False
    settings = get_settings()
    signature = repr((sorted(entries), settings.embedding_model, settings.embedding_dimensions))
    job_id = "knowledge-index-" + hashlib.sha256(signature.encode()).hexdigest()[:40]
    try:
        Queue(QUEUE_NAME, connection=redis_connection()).enqueue(
            "app.services.vector_index.index_entries",
            entries,
            job_id=job_id,
            unique=True,
            job_timeout=600,
            result_ttl=0,
            failure_ttl=60,
            description="Update course knowledge vectors",
        )
        return True
    except DuplicateJobError:
        return True
    except RedisError:
        logger.warning("Vector index queue unavailable; chunks remain pending.")
        return False


def enqueue_course_index(db, course_id, *, force=False):
    course = db.get(Course, course_id)
    if course:
        handled = account_index.enqueue_account(db, course.user_id, course_id, force=force)
        if handled is not None:
            return handled
    entries = pending_entries(db, course_id, force=force)
    return all(
        enqueue_index(entries[offset : offset + 20]) for offset in range(0, len(entries), 20)
    )


def index_entries(entries):
    settings = get_settings()
    expected = dict(entries)
    if not expected or not configured():
        return {"indexed": 0, "tokens": 0}
    with SessionLocal() as db:
        rows = db.execute(
            select(KnowledgeChunk, KnowledgePoint.version)
            .join(KnowledgePoint)
            .where(
                KnowledgePoint.id.in_(expected),
                KnowledgePoint.status == "active",
                KnowledgeChunk.version == KnowledgePoint.version,
            )
            .order_by(KnowledgeChunk.knowledge_id, KnowledgeChunk.position)
        ).all()
        groups = defaultdict(list)
        for chunk, version in rows:
            course = db.get(Course, chunk.course_id)
            if profile_for(db, course.user_id, "embedding"):
                continue
            if expected[chunk.knowledge_id] == version:
                groups[chunk.knowledge_id].append(chunk)
        groups = {
            key: rows
            for key, rows in groups.items()
            if any(
                row.embedding_status != "ready"
                or row.embedding is None
                or row.embedding_model != settings.embedding_model
                or row.embedding_dimensions != settings.embedding_dimensions
                or row.embedding_fingerprint != fingerprint(default_config("embedding"))
                for row in rows
            )
        }
        texts = [chunk.text for rows in groups.values() for chunk in rows]
    if not texts:
        return {"indexed": 0, "tokens": 0}
    try:
        result = EmbeddingClient().embed(texts)
    except ModelAPIError:
        with SessionLocal() as db:
            for key in groups:
                db.execute(
                    update(KnowledgeChunk)
                    .where(
                        KnowledgeChunk.knowledge_id == key,
                        KnowledgeChunk.version == expected[key],
                    )
                    .values(
                        embedding_status="failed",
                        embedding_error="向量生成暂时失败，可稍后重试。",
                        embedding_retry_at=utcnow() + timedelta(minutes=1),
                    )
                )
            db.commit()
        return {"indexed": 0, "failed": len(groups), "tokens": 0}
    indexed, offset = 0, 0
    with SessionLocal() as db:
        for key, chunks in groups.items():
            vectors = result.vectors[offset : offset + len(chunks)]
            indexed += store_embeddings(db, key, expected[key], vectors, result.model)
            offset += len(chunks)
        db.commit()
    return {"indexed": indexed, "tokens": result.total_tokens}


def index_course(course_id):
    profile_id = None
    with SessionLocal() as db:
        course = db.get(Course, course_id)
        profile = (
            (
                profile_for(db, course.user_id, "embedding", pending=True)
                or profile_for(db, course.user_id, "embedding")
            )
            if course
            else None
        )
        if profile:
            profile_id = profile.id
            entries = account_index.pending_entries(db, profile, course_id, force=True)
        else:
            entries = pending_entries(db, course_id, force=True)
    indexed = failed = tokens = 0
    if profile_id and not entries:
        return account_index.index_profile(profile_id, [])
    for offset in range(0, len(entries), 20):
        result = (
            account_index.index_profile(profile_id, entries[offset : offset + 20])
            if profile_id
            else index_entries(entries[offset : offset + 20])
        )
        indexed += result["indexed"]
        failed += result.get("failed", 0)
        tokens += result["tokens"]
    return {"indexed": indexed, "failed": failed, "tokens": tokens}


def index_status(db, course_id):
    course = db.get(Course, course_id)
    profile = profile_for(db, course.user_id, "embedding") if course else None
    if profile:
        result = account_index.status(db, profile, course_id)
        pending = profile_for(db, course.user_id, "embedding", pending=True)
        if pending:
            result["rebuild"] = {
                **account_index.status(db, pending, course_id),
                "model": pending.config["model"],
            }
        return result
    settings = get_settings()
    ready_condition = and_(
        KnowledgeChunk.embedding_status == "ready",
        KnowledgeChunk.embedding.is_not(None),
        KnowledgeChunk.embedding_model == settings.embedding_model,
        KnowledgeChunk.embedding_dimensions == settings.embedding_dimensions,
        KnowledgeChunk.embedding_fingerprint == fingerprint(default_config("embedding")),
    )
    total, ready, failed = db.execute(
        select(
            func.count(KnowledgeChunk.id),
            func.count(KnowledgeChunk.id).filter(ready_condition),
            func.count(KnowledgeChunk.id).filter(KnowledgeChunk.embedding_status == "failed"),
        )
        .select_from(KnowledgeChunk)
        .join(KnowledgePoint)
        .where(
            KnowledgeChunk.course_id == course_id,
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.status == "active",
            KnowledgeChunk.version == KnowledgePoint.version,
        )
    ).one()
    return {
        "total": total,
        "ready": ready,
        "pending": total - ready - failed,
        "failed": failed,
        "embedding_configured": configured(),
    }
