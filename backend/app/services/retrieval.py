import logging
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import defer, selectinload

from app.core.model_runtime import use_model_settings
from app.models import Course, KnowledgeChunk, KnowledgeEmbedding, KnowledgePoint
from app.services.account_models import default_config, fingerprint, profile_for, resolve_settings
from app.services.embeddings import EmbeddingClient
from app.services.model_api import ModelAPIError, model_failure_message
from app.services.query_embeddings import query_embedding
from app.services.retrieval_notation import notation_score, question_notation
from app.services.sources import source_snapshot
from app.services.vector_index import index_status

if TYPE_CHECKING:
    from app.services.chat_pdf import ReferencedPageImage

logger = logging.getLogger("learnflow.retrieval")


@dataclass(frozen=True)
class RetrievedContext:
    items: list[dict]
    mode: str
    warnings: list[str]
    images: list[bytes] | None = None
    pdf_page_limit: int = 0
    pdf_page_images: tuple["ReferencedPageImage", ...] = ()
    pdf_read_attempted: bool = False


def lexical_score(text: str, question: str) -> int:
    terms = set(re.findall(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]{2,}", question.lower()))
    for sequence in list(terms):
        if re.fullmatch(r"[\u4e00-\u9fff]+", sequence):
            terms.update(sequence[start : start + 2] for start in range(len(sequence) - 1))
    value = text.lower()
    return sum(min(len(term), 12) for term in terms if term in value)


def retrieve_course(db, course_id, user_id, question, *, limit=6, original_question=None):
    if limit < 1:
        return RetrievedContext([], "empty", [])
    settings = resolve_settings(db, user_id)
    profile = profile_for(db, user_id, "embedding")
    statement = (
        select(KnowledgeChunk, KnowledgePoint)
        .join(KnowledgePoint)
        .join(Course, Course.id == KnowledgePoint.course_id)
        .options(selectinload(KnowledgePoint.sources))
        .where(
            Course.id == course_id,
            Course.user_id == user_id,
            KnowledgePoint.course_id == course_id,
            KnowledgeChunk.course_id == course_id,
            KnowledgePoint.status == "active",
            KnowledgeChunk.version == KnowledgePoint.version,
        )
    )
    if db.bind.dialect.name == "postgresql":
        statement = statement.options(defer(KnowledgeChunk.embedding))
    status = index_status(db, course_id)
    warnings, vector_rows = [], []
    if status["ready"] and status["embedding_configured"]:
        try:
            with use_model_settings(settings):
                vector = query_embedding(
                    settings,
                    user_id,
                    course_id,
                    question,
                    lambda text: EmbeddingClient().embed([text]).vectors[0],
                )
            if profile:
                semantic = statement.join(
                    KnowledgeEmbedding, KnowledgeEmbedding.chunk_id == KnowledgeChunk.id
                ).where(
                    KnowledgeEmbedding.profile_id == profile.id,
                    KnowledgeEmbedding.status == "ready",
                    KnowledgeEmbedding.embedding.is_not(None),
                )
                vector_column = KnowledgeEmbedding.embedding
            else:
                vector_column = KnowledgeChunk.embedding
                semantic = statement.where(
                    KnowledgeChunk.embedding_status == "ready",
                    KnowledgeChunk.embedding.is_not(None),
                    KnowledgeChunk.embedding_model == settings.embedding_model,
                    KnowledgeChunk.embedding_dimensions == settings.embedding_dimensions,
                    KnowledgeChunk.embedding_fingerprint
                    == fingerprint(default_config("embedding", settings)),
                )
            if db.bind.dialect.name == "postgresql":
                distance = vector_column.cosine_distance(vector)
                vector_rows = [
                    (chunk, point, 1 - float(value))
                    for chunk, point, value in db.execute(
                        semantic.add_columns(distance).order_by(distance).limit(24)
                    )
                ]
            else:
                for chunk, point in db.execute(semantic):
                    stored_vector = (
                        db.get(KnowledgeEmbedding, (chunk.id, profile.id)).embedding
                        if profile
                        else chunk.embedding
                    )
                    magnitude = math.sqrt(
                        sum(value * value for value in vector)
                        * sum(value * value for value in stored_vector)
                    )
                    if magnitude:
                        vector_rows.append(
                            (
                                chunk,
                                point,
                                sum(a * b for a, b in zip(vector, stored_vector, strict=True))
                                / magnitude,
                            )
                        )
                vector_rows.sort(key=lambda row: -row[2])
            vector_rows = [row for row in vector_rows if row[2] >= settings.rag_min_similarity]
        except ModelAPIError as exc:
            logger.warning("query_embedding_failed course=%s code=%s", course_id, exc.code)
            reason = (
                model_failure_message(exc, "Embedding")
                if exc.code in {"not_purchased", "unauthorized", "forbidden", "rate_limited"}
                else "语义检索暂时不可用。"
            )
            warnings.append(reason + "本次使用关键词查找。")
    elif status["total"]:
        warnings.append("知识索引尚未完成，本次使用关键词查找。")
    if status["ready"] < status["total"] and vector_rows:
        warnings.append("部分知识仍在建立索引，本次同时使用关键词查找。")
    # 第一版知识规模有限，关键词补查只在当前课程的有效版本中进行。
    rules, operators = question_notation(original_question or question)
    if original_question and original_question != question and not (rules or operators):
        rules, operators = question_notation(question)
    lexical, exact = [], {}
    no_match = (0, 0)
    for chunk, point in db.execute(statement):
        if score := lexical_score(chunk.text, question):
            lexical.append((chunk, point, score))
        if rules or operators:
            match = notation_score(chunk.text, rules, operators)
            if match != no_match:
                exact[chunk.id] = (chunk, point, match)
    lexical = sorted(lexical, key=lambda row: (-row[2], row[0].id))[:24]
    fused = {}
    for rows in [vector_rows, lexical]:
        for position, (chunk, point, _) in enumerate(rows):
            entry = fused.setdefault(chunk.id, [chunk, point, 0.0])
            entry[2] += 1 / (30 + position)
    selected, per_point = [], {}
    for chunk, point, _ in sorted(fused.values(), key=lambda row: -row[2]):
        if per_point.get(point.id, 0) >= 2:
            continue
        per_point[point.id] = per_point.get(point.id, 0) + 1
        selected.append((chunk, point))
        if len(selected) == limit:
            break
    if exact:
        fused_scores = {chunk_id: row[2] for chunk_id, row in fused.items()}
        chunk, point, best = max(
            exact.values(),
            key=lambda row: (row[2], fused_scores.get(row[0].id, 0), row[0].id),
        )
        selected_score = max(
            (exact[picked.id][2] for picked, _ in selected if picked.id in exact),
            default=no_match,
        )
        if best > selected_score:
            # 引用同一知识点的片段仍受数量限制。
            if per_point.get(point.id, 0) >= 2:
                index = max(i for i, (_, picked) in enumerate(selected) if picked.id == point.id)
                selected[index] = (chunk, point)
            elif len(selected) < limit:
                selected.append((chunk, point))
            else:
                selected[-1] = (chunk, point)
    items = [
        {
            "key": f"K{rank}",
            "chunk_id": chunk.id,
            "knowledge_id": point.id,
            "version": point.version,
            "title": point.title,
            "text": chunk.text,
            "sources": source_snapshot(point.sources),
        }
        for rank, (chunk, point) in enumerate(selected, start=1)
    ]
    has_text_match = bool(lexical or exact)
    mode = (
        "hybrid"
        if vector_rows and has_text_match
        else "semantic"
        if vector_rows
        else "text"
        if has_text_match
        else "empty"
    )
    return RetrievedContext(items, mode, warnings)
