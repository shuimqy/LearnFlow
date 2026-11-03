import hashlib
import logging
from datetime import timedelta

from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import DuplicateJobError
from sqlalchemy import and_, func, or_, select

from app.core.database import SessionLocal
from app.core.model_runtime import use_model_settings
from app.models import (
    AccountModels,
    Course,
    KnowledgeChunk,
    KnowledgeEmbedding,
    KnowledgePoint,
    ModelProfile,
    User,
)
from app.models.base import utcnow
from app.services.account_models import is_configured, settings_for_profile
from app.services.embeddings import EmbeddingClient
from app.services.extraction_queue import QUEUE_NAME, redis_connection
from app.services.model_api import ModelAPIError

logger = logging.getLogger(__name__)


def chunks_query(profile, course_id=None):
    statement = (
        select(KnowledgeChunk)
        .join(KnowledgePoint)
        .join(Course, Course.id == KnowledgePoint.course_id)
        .where(
            Course.user_id == profile.user_id,
            KnowledgeChunk.course_id == Course.id,
            KnowledgePoint.status == "active",
            KnowledgeChunk.version == KnowledgePoint.version,
        )
    )
    if course_id:
        statement = statement.where(Course.id == course_id)
    return statement


def status(db, profile, course_id=None):
    ids = chunks_query(profile, course_id).with_only_columns(KnowledgeChunk.id).subquery()
    total, ready, failed = db.execute(
        select(
            func.count(ids.c.id),
            func.count(ids.c.id).filter(
                and_(
                    KnowledgeEmbedding.status == "ready", KnowledgeEmbedding.embedding.is_not(None)
                )
            ),
            func.count(ids.c.id).filter(KnowledgeEmbedding.status == "failed"),
        )
        .select_from(ids)
        .outerjoin(
            KnowledgeEmbedding,
            and_(
                KnowledgeEmbedding.chunk_id == ids.c.id, KnowledgeEmbedding.profile_id == profile.id
            ),
        )
    ).one()
    return {
        "total": total,
        "ready": ready,
        "failed": failed,
        "pending": total - ready - failed,
        "embedding_configured": is_configured(settings_for_profile(profile), "embedding"),
    }


def pending_entries(db, profile, course_id=None, *, force=False):
    statement = (
        chunks_query(profile, course_id)
        .outerjoin(
            KnowledgeEmbedding,
            and_(
                KnowledgeEmbedding.chunk_id == KnowledgeChunk.id,
                KnowledgeEmbedding.profile_id == profile.id,
            ),
        )
        .where(
            or_(
                KnowledgeEmbedding.status.is_(None),
                KnowledgeEmbedding.status != "ready",
                KnowledgeEmbedding.embedding.is_(None),
            )
        )
    )
    if not force:
        statement = statement.where(
            or_(KnowledgeEmbedding.retry_at.is_(None), KnowledgeEmbedding.retry_at <= utcnow())
        )
    return list(
        db.execute(
            statement.with_only_columns(KnowledgePoint.id, KnowledgePoint.version)
            .distinct()
            .order_by(KnowledgePoint.id)
        ).tuples()
    )


def enqueue_profile(profile_id, entries):
    if not entries:
        return True
    signature = repr((profile_id, sorted(entries)))
    try:
        Queue(QUEUE_NAME, connection=redis_connection()).enqueue(
            "app.services.account_index.index_profile",
            profile_id,
            entries,
            job_id="account-index-" + hashlib.sha256(signature.encode()).hexdigest()[:40],
            unique=True,
            job_timeout=600,
            result_ttl=0,
            failure_ttl=60,
            description="Update account knowledge vectors",
        )
        return True
    except DuplicateJobError:
        return True
    except RedisError:
        logger.warning("Account vector queue unavailable; index remains pending.")
        return False


def enqueue_account(db, user_id, course_id=None, *, force=False):
    account = db.get(AccountModels, user_id)
    if not account or not account.embedding_id:
        return None
    success = True
    for identity in (account.pending_embedding_id or account.embedding_id,):
        profile = db.get(ModelProfile, identity) if identity else None
        if not profile:
            continue
        if not is_configured(settings_for_profile(profile), "embedding"):
            success = False
            continue
        entries = pending_entries(db, profile, course_id, force=force)
        for offset in range(0, len(entries), 20):
            success = enqueue_profile(identity, entries[offset : offset + 20]) and success
    return success


def dispatch_entries(db, entries):
    legacy = []
    expected = dict(entries)
    rows = db.execute(
        select(KnowledgePoint, Course.user_id).join(Course).where(KnowledgePoint.id.in_(expected))
    )
    grouped = {}
    for point, user_id in rows:
        if point.version != expected[point.id] or point.status != "active":
            continue
        account = db.get(AccountModels, user_id)
        if not account or not account.embedding_id:
            legacy.append((point.id, point.version))
        else:
            for profile_id in (account.pending_embedding_id or account.embedding_id,):
                if profile_id:
                    grouped.setdefault(profile_id, []).append((point.id, point.version))
    success = True
    for profile_id, batch in grouped.items():
        profile = db.get(ModelProfile, profile_id)
        if is_configured(settings_for_profile(profile), "embedding"):
            success = enqueue_profile(profile_id, batch) and success
    return legacy, success


def current_profile(db, profile_id, *, lock=False):
    profile = db.get(ModelProfile, profile_id)
    if not profile:
        return None
    if lock:
        db.scalar(select(User).where(User.id == profile.user_id).with_for_update())
    account = db.scalar(
        select(AccountModels)
        .where(AccountModels.user_id == profile.user_id)
        .execution_options(populate_existing=True)
    )
    if not account or profile_id not in (account.embedding_id, account.pending_embedding_id):
        return None
    return profile


def try_activate(db, user_id):
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    account = db.scalar(
        select(AccountModels)
        .where(AccountModels.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if not account or not account.pending_embedding_id:
        return False
    profile = db.get(ModelProfile, account.pending_embedding_id)
    progress = status(db, profile)
    if progress["ready"] != progress["total"]:
        return False
    old_id = account.embedding_id
    account.embedding_id, account.pending_embedding_id = profile.id, None
    account.version += 1
    db.flush()
    if old_id and old_id != profile.id:
        db.delete(db.get(ModelProfile, old_id))
    db.commit()
    return True


def index_profile(profile_id, entries):
    expected = dict(entries)
    with SessionLocal() as db:
        profile = current_profile(db, profile_id)
        if not profile:
            return {"indexed": 0, "tokens": 0}
        user_id = profile.user_id
        settings = settings_for_profile(profile)
        if not is_configured(settings, "embedding"):
            return {"indexed": 0, "tokens": 0}
        rows = db.scalars(
            chunks_query(profile)
            .where(KnowledgePoint.id.in_(expected))
            .order_by(KnowledgeChunk.knowledge_id, KnowledgeChunk.position)
        ).all()
        chunks = []
        for row in rows:
            saved = db.get(KnowledgeEmbedding, (row.id, profile_id))
            if row.version == expected[row.knowledge_id] and (
                not saved or saved.status != "ready" or saved.embedding is None
            ):
                chunks.append((row.id, row.knowledge_id, row.version, row.text))
    if not chunks:
        with SessionLocal() as db:
            try_activate(db, user_id)
        return {"indexed": 0, "tokens": 0}
    error = None
    result = None
    try:
        with use_model_settings(settings):
            result = EmbeddingClient().embed([row[3] for row in chunks])
    except ModelAPIError:
        error = "向量生成失败，请检查账号模型配置后重试。"
    indexed = 0
    with SessionLocal() as db:
        if not current_profile(db, profile_id, lock=True):
            return {"indexed": 0, "tokens": result.total_tokens if result else 0}
        valid = {
            chunk.id
            for chunk in db.scalars(
                chunks_query(profile).where(KnowledgeChunk.id.in_([item[0] for item in chunks]))
            )
        }
        for position, (chunk_id, _, _, _) in enumerate(chunks):
            if chunk_id not in valid:
                continue
            saved = db.get(KnowledgeEmbedding, (chunk_id, profile_id))
            if saved and saved.status == "ready" and saved.embedding is not None:
                continue
            saved = saved or KnowledgeEmbedding(chunk_id=chunk_id, profile_id=profile_id)
            if error:
                saved.status, saved.error, saved.retry_at = (
                    "failed",
                    error,
                    utcnow() + timedelta(minutes=1),
                )
            else:
                saved.embedding, saved.status = result.vectors[position], "ready"
                saved.error, saved.retry_at, saved.embedded_at = None, None, utcnow()
                indexed += 1
            db.add(saved)
        db.commit()
        try_activate(db, user_id)
    return {
        "indexed": indexed,
        "failed": len(chunks) if error else 0,
        "tokens": result.total_tokens if result else 0,
    }
