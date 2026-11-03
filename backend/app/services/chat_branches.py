import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import select

from app.models import ChatMessage, Conversation
from app.services.chat_images import image_rows_for


def historical_text(value):
    return re.sub(r"\[K\d+\]", "（历史引用，须核对当前知识版本）", value)


def context_snapshot(db, parent, message, anchor, mode, user_id):
    question = db.scalar(
        select(ChatMessage).where(
            ChatMessage.conversation_id == parent.id,
            ChatMessage.request_id == message.request_id,
            ChatMessage.role == "user",
            ChatMessage.sequence < message.sequence,
        )
    )
    if not question:
        raise HTTPException(409, "原问题不存在，无法创建完整的分支上下文")
    images = image_rows_for(db, parent, question, user_id)
    prefix = (
        "以下是创建分支时保存的对话背景，讨论知识时须使用当前有效的课程依据。\n\n"
        + f"选中片段：\n{anchor}\n\n原问题：\n{question.content or '（图片提问）'}"
        + (
            "\n\n用户附图的识别内容（可能有误）：\n" + question.image_context
            if question.image_context
            else ""
        )
    )
    messages = []
    truncated = False
    if mode != "minimal":
        rows = list(
            reversed(
                db.scalars(
                    select(ChatMessage)
                    .where(
                        ChatMessage.conversation_id == parent.id,
                        ChatMessage.status == "completed",
                        ChatMessage.sequence < question.sequence,
                    )
                    .order_by(ChatMessage.sequence.desc())
                    .limit(20 if mode == "full" else 4)
                ).all()
            )
        )
        prior_budget = 10000 if mode == "full" else 4000
        for row in reversed(rows):
            text = historical_text(row.content)
            kept = text[: min(2000, prior_budget)]
            if kept:
                messages.insert(0, {"role": row.role, "content": kept})
                prior_budget -= len(kept)
            truncated = truncated or len(kept) < len(text)
        messages.append({"role": "user", "content": historical_text(prefix)})
        answer = historical_text(
            message.content
            + ("\n\n补充解释：\n" + message.supplement if message.supplement else "")
        )
        budget = max(4000, 32000 - sum(len(item["content"]) for item in messages))
        messages.append({"role": "assistant", "content": answer[:budget]})
        truncated = truncated or len(answer) > budget
    else:
        messages = [{"role": "user", "content": historical_text(prefix)}]
    return {
        "original_question": question.content or "（图片提问）",
        "source_image_ids": [image.id for image in images],
        "source_images": [
            {
                field: getattr(image, field)
                for field in ("id", "filename", "media_type", "size", "width", "height")
            }
            for image in images
        ],
        "parent_answer": message.content,
        "parent_supplement": message.supplement,
        "parent_sequence": message.sequence,
        "source_citations": message.citations,
        "source_hash": hashlib.sha256(message.content.encode()).hexdigest(),
        "messages": messages,
        "truncated": truncated,
    }


def create_branch(db, parent, user_id, payload):
    if parent.parent_conversation_id:
        raise HTTPException(400, "当前支持从主对话创建一级分支")
    existing = db.scalar(
        select(Conversation).where(
            Conversation.parent_conversation_id == parent.id,
            Conversation.branch_request_id == str(payload.request_id),
        )
    )
    if existing:
        if (
            existing.parent_message_id != str(payload.parent_message_id)
            or existing.context_mode != payload.context_mode
            or existing.context_snapshot.get("initial_question") != payload.question
            or existing.context_snapshot.get("requested_anchor", "") != payload.anchor_text
        ):
            raise HTTPException(409, "同一请求标识不能用于不同的分支问题")
        return existing
    message = db.scalar(
        select(ChatMessage).where(
            ChatMessage.id == str(payload.parent_message_id),
            ChatMessage.conversation_id == parent.id,
            ChatMessage.role == "assistant",
            ChatMessage.status == "completed",
        )
    )
    if not message or not message.content.strip():
        raise HTTPException(404, "只能从当前主对话已完成的回答创建分支")
    anchor = payload.anchor_text.strip() or message.content[:6000]
    snapshot = context_snapshot(db, parent, message, anchor, payload.context_mode, user_id)
    snapshot.update(initial_question=payload.question, requested_anchor=payload.anchor_text)
    branch = Conversation(
        course_id=parent.course_id,
        title=payload.question[:60],
        parent_conversation_id=parent.id,
        parent_message_id=message.id,
        branch_request_id=str(payload.request_id),
        anchor_text=anchor,
        context_mode=payload.context_mode,
        context_snapshot=snapshot,
    )
    db.add(branch)
    db.flush()
    db.add_all(
        [
            ChatMessage(
                conversation_id=branch.id,
                sequence=1,
                request_id=str(payload.request_id),
                role="user",
                content=payload.question,
            ),
            ChatMessage(
                conversation_id=branch.id,
                sequence=2,
                request_id=str(payload.request_id),
                role="assistant",
                status="pending",
                workflow_stage="preparing",
            ),
        ]
    )
    db.commit()
    return branch
