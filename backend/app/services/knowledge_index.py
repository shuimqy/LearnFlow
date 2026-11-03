import hashlib
import math

from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

from app.models import KnowledgeChunk, KnowledgePoint
from app.models.base import utcnow


def split_content(text: str, size: int = 1200, overlap: int = 240) -> list[str]:
    result = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary >= 0:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            result.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return result


def rebuild_chunks(db: Session, point: KnowledgePoint) -> None:
    # 与知识修订放在同一事务，提交后不会留下仍可检索的旧内容。
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == point.id))
    if point.status != "active":
        return
    db.info.setdefault("knowledge_to_index", set()).add((point.id, point.version))
    prefix = f"# {point.title}\n\n" + (f"{point.summary}\n\n" if point.summary else "")
    for position, content in enumerate(split_content(point.content)):
        text = prefix + content
        db.add(
            KnowledgeChunk(
                course_id=point.course_id,
                knowledge_id=point.id,
                version=point.version,
                position=position,
                text=text,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                embedding_status="pending",
            )
        )


def store_embeddings(
    db: Session,
    knowledge_id: str,
    version: int,
    vectors: list[list[float]],
    model: str,
) -> bool:
    point = db.scalar(
        select(KnowledgePoint)
        .where(KnowledgePoint.id == knowledge_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not point or point.status != "active" or point.version != version:
        return False
    chunks = list(
        db.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.knowledge_id == knowledge_id, KnowledgeChunk.version == version)
            .order_by(KnowledgeChunk.position)
        )
    )
    if not model.strip() or len(chunks) != len(vectors) or not vectors:
        raise ValueError("Embedding batch does not match the current chunks")
    dimension = len(vectors[0])
    from app.services.account_models import default_config, fingerprint

    identity = fingerprint({**default_config("embedding"), "model": model, "dimensions": dimension})
    if not dimension or any(
        len(vector) != dimension or any(not math.isfinite(x) for x in vector) for vector in vectors
    ):
        raise ValueError("Invalid embedding dimensions or values")
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_model = model
        chunk.embedding_fingerprint = identity
        chunk.embedding_dimensions = dimension
        chunk.embedding_error = None
        chunk.embedding_retry_at = None
        chunk.embedding_status = "ready"
        chunk.embedded_at = utcnow()
    db.flush()
    return True


@event.listens_for(Session, "after_commit")
def queue_committed_chunks(db):
    entries = db.info.pop("knowledge_to_index", set())
    if entries:
        from app.core.config import get_settings

        if get_settings().embedding_auto_index:
            from app.services.vector_index import enqueue_index

            ordered = sorted(entries)
            for offset in range(0, len(ordered), 20):
                enqueue_index(ordered[offset : offset + 20])


@event.listens_for(Session, "after_rollback")
def discard_uncommitted_index(db):
    db.info.pop("knowledge_to_index", None)
