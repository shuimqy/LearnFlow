import hashlib

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import ChatMessage, Course, KnowledgeChunk, KnowledgePoint
from app.services.sources import source_snapshot


def current_evidence(db, course_id, user_id, candidates):
    if not candidates:
        return []
    rows = db.execute(
        select(KnowledgeChunk, KnowledgePoint)
        .join(KnowledgePoint, KnowledgePoint.id == KnowledgeChunk.knowledge_id)
        .join(Course, Course.id == KnowledgePoint.course_id)
        .options(selectinload(KnowledgePoint.sources))
        .where(
            Course.id == course_id,
            Course.user_id == user_id,
            KnowledgeChunk.course_id == course_id,
            KnowledgeChunk.id.in_([item.get("chunk_id") for item in candidates]),
            KnowledgePoint.status == "active",
            KnowledgeChunk.version == KnowledgePoint.version,
        )
        .execution_options(populate_existing=True)
    ).all()
    by_id = {chunk.id: (chunk, point) for chunk, point in rows}
    result, seen = [], set()
    for item in candidates:
        pair = by_id.get(item.get("chunk_id"))
        if not pair:
            continue
        chunk, point = pair
        if item.get("version") != point.version or chunk.id in seen:
            continue
        seen.add(chunk.id)
        result.append(
            {
                "key": f"K{len(result) + 1}",
                "chunk_id": chunk.id,
                "knowledge_id": point.id,
                "version": point.version,
                "title": point.title,
                "text": chunk.text,
                "sources": source_snapshot(point.sources),
            }
        )
        if len(result) == 6:
            break
    return result


def evidence_for(db, conversation, sequence, user_id):
    rows = db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.sequence < sequence,
            ChatMessage.role == "assistant",
            ChatMessage.status == "completed",
        )
        .order_by(ChatMessage.sequence.desc())
        .limit(4)
    ).all()
    candidates = [citation for row in rows for citation in row.citations]
    if conversation.parent_conversation_id:
        snapshot = conversation.context_snapshot
        citations = snapshot.get("source_citations")
        if citations is None:
            # 旧分支没有引用快照，只能读取分叉时的同一条原回答。
            source = db.scalar(
                select(ChatMessage).where(
                    ChatMessage.id == conversation.parent_message_id,
                    ChatMessage.conversation_id == conversation.parent_conversation_id,
                    ChatMessage.status == "completed",
                )
            )
            if source and hashlib.sha256(source.content.encode()).hexdigest() == snapshot.get(
                "source_hash"
            ):
                citations = source.citations
        candidates.extend(citations or [])
    return current_evidence(db, conversation.course_id, user_id, candidates)


def memory_for(db, conversation, previous_question):
    first = db.scalar(
        select(ChatMessage.content)
        .where(ChatMessage.conversation_id == conversation.id, ChatMessage.role == "user")
        .order_by(ChatMessage.sequence)
        .limit(1)
    )
    return {
        "first_question": first if first != "" else "（图片提问）",
        "previous_question": previous_question,
        "branch_original_question": conversation.context_snapshot.get("original_question"),
        "history_scope": "只提供有限的已保存历史；看不到的记录不能编造，也不能把历史说法视为已核实知识。",
    }
