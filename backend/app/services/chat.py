import logging
import re
from datetime import UTC, timedelta

from fastapi import HTTPException
from langsmith import tracing_context
from sqlalchemy import func, select

from app.models import ChatGraphThread, ChatMessage, Conversation, Course, KnowledgePoint
from app.models.base import new_id, utcnow
from app.schemas.chat import AnswerDraft
from app.services.account_models import resolve_settings
from app.services.chat_checkpoints import conversation_checkpointer, thread_id
from app.services.chat_context import evidence_for, memory_for
from app.services.chat_generation import generate_answer, generate_conversation, validate_answer
from app.services.chat_graph import ChatRuntime, build_chat_graph
from app.services.chat_images import add_images, conversation_images
from app.services.chat_intent import plan_question
from app.services.chat_vision import describe_images
from app.services.model_api import ModelAPIError, model_failure_message

logger = logging.getLogger("learnflow.chat")


def owned_conversation(db, course_id, conversation_id, user_id, *, lock=False):
    statement = (
        select(Conversation)
        .join(Course)
        .where(
            Conversation.id == conversation_id,
            Conversation.course_id == course_id,
            Course.user_id == user_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update(of=Conversation)
    conversation = db.scalar(statement)
    if not conversation:
        raise HTTPException(404, "对话不存在")
    return conversation


def processing(conversation):
    return bool(
        conversation.processing_token
        and conversation.processing_started_at
        and utcnow() - conversation.processing_started_at.replace(tzinfo=UTC) < timedelta(minutes=5)
    )


def recover_interrupted(db, conversation):
    if not conversation.processing_token or processing(conversation):
        return
    pending = db.scalars(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conversation.id, ChatMessage.status == "generating"
        )
    ).all()
    for message in pending:
        message.status, message.error = "failed", "上次回答已中断，可以重试。"
        message.workflow_stage = "failed"
    conversation.processing_token, conversation.processing_started_at = None, None
    db.commit()


def history_for(db, conversation_id, sequence):
    rows = db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.sequence < sequence,
            ChatMessage.status == "completed",
        )
        .order_by(ChatMessage.sequence.desc())
        .limit(10)
    ).all()
    history, budget = [], 10000
    for row in rows:
        content = row.content + ("\n\n补充解释：\n" + row.supplement if row.supplement else "")
        if row.image_context:
            content += "\n\n用户附图的识别内容（可能存在识别误差）：\n" + row.image_context
        text = re.sub(r"\[K\d+\]", "（历史引用，须核对当前知识版本）", content)
        text = text[: min(2000, budget)]
        if not text:
            break
        history.append({"role": row.role, "content": text})
        budget -= len(text)
    own_history = list(reversed(history))
    conversation = db.get(Conversation, conversation_id)
    if conversation and conversation.parent_conversation_id:
        return [*conversation.context_snapshot.get("messages", []), *own_history]
    return own_history


def ask_question(db, course_id, conversation_id, user_id, payload, *, images=None):
    conversation = owned_conversation(db, course_id, conversation_id, user_id, lock=True)
    recover_interrupted(db, conversation)
    conversation = owned_conversation(db, course_id, conversation_id, user_id, lock=True)
    request_id = str(payload.request_id)
    existing = db.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id, ChatMessage.request_id == request_id)
        .order_by(ChatMessage.sequence)
    ).all()
    if existing and existing[0].content != payload.content:
        raise HTTPException(409, "同一请求标识不能用于不同的问题")
    if (
        existing
        and images is not None
        and [image.sha256 for image in existing[0].images] != [image.sha256 for image in images]
    ):
        raise HTTPException(409, "同一请求标识不能用于不同的图片")
    if existing and existing[-1].role == "assistant" and existing[-1].status == "completed":
        return existing[-1]
    current_images = images or (existing[0].images if existing else [])
    if not payload.content and not current_images:
        raise HTTPException(422, "请输入问题或添加图片")
    settings = resolve_settings(db, user_id)
    if current_images and not settings.llm_vision:
        raise HTTPException(
            422, "当前账号的 LLM 未启用图片识别，请在账号设置中更换或启用支持图片的模型。"
        )
    if processing(conversation):
        raise HTTPException(409, "这段对话正在生成回答，请稍后查看")
    if not existing and db.scalar(
        select(ChatMessage.id)
        .where(ChatMessage.conversation_id == conversation_id, ChatMessage.status == "pending")
        .limit(1)
    ):
        raise HTTPException(409, "请先生成分支中已保存问题的回答")
    token = new_id()
    conversation.processing_token, conversation.processing_started_at = token, utcnow()
    if existing:
        user_message, assistant = existing
        assistant.status, assistant.error = "generating", None
        assistant.workflow_stage = "preparing"
    else:
        sequence = (
            db.scalar(
                select(func.max(ChatMessage.sequence)).where(
                    ChatMessage.conversation_id == conversation_id
                )
            )
            or 0
        ) + 1
        user_message = ChatMessage(
            conversation_id=conversation_id,
            sequence=sequence,
            request_id=request_id,
            role="user",
            content=payload.content,
        )
        assistant = ChatMessage(
            conversation_id=conversation_id,
            sequence=sequence + 1,
            request_id=request_id,
            role="assistant",
            status="generating",
            workflow_stage="preparing",
        )
        db.add_all([user_message, assistant])
        if images:
            add_images(user_message, images)
        if sequence == 1 and conversation.title == "新对话":
            conversation.title = payload.content[:60] or "图片提问"
    conversation.updated_at = utcnow()
    db.flush()
    assistant_id = assistant.id
    identity = thread_id(user_id, course_id, conversation_id)
    graph_thread = db.get(ChatGraphThread, identity)
    if graph_thread:
        graph_thread.run_id = token
    else:
        db.add(ChatGraphThread(thread_id=identity, conversation_id=conversation_id, run_id=token))
    history = history_for(db, conversation_id, user_message.sequence)
    previous_question = db.scalar(
        select(func.coalesce(func.nullif(ChatMessage.content, ""), "（图片提问）"))
        .where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role == "user",
            ChatMessage.sequence < user_message.sequence,
        )
        .order_by(ChatMessage.sequence.desc())
        .limit(1)
    )
    if previous_question is None and conversation.parent_conversation_id:
        previous_question = conversation.context_snapshot.get("original_question")
    candidates = evidence_for(db, conversation, user_message.sequence, user_id)
    memory = memory_for(db, conversation, previous_question)
    image_data = (
        conversation_images(db, conversation, user_message, user_id) if settings.llm_vision else []
    )
    memory["has_images"] = bool(image_data)
    db.commit()
    try:
        runtime = ChatRuntime(
            db=db,
            user_id=user_id,
            course_id=course_id,
            plan=plan_question,
            converse=generate_conversation,
            generate=generate_answer,
            images=image_data,
            new_images=bool(user_message.images),
            describe=describe_images,
            remember_images=lambda text: remember_image_context(
                db, course_id, conversation_id, user_id, token, user_message.id, text
            ),
            stage=lambda value: update_stage(
                db, course_id, conversation_id, user_id, token, assistant_id, value
            ),
            persist=lambda state: persist_answer(
                db, course_id, conversation_id, user_id, token, assistant_id, state
            ),
        )
        state = {
            "request_id": request_id,
            "question": payload.content,
            "effective_question": payload.content,
            "image_context": user_message.image_context,
            "has_images": bool(image_data),
            "history": history,
            "memory": memory,
            "candidates": candidates,
            "retrieved": False,
            "previous_question": previous_question,
            "intent": "course",
            "query": "",
            "items": [],
            "retrieval_mode": "empty",
            "warnings": [],
            "answer": None,
            "model": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "saved": False,
        }
        with (
            tracing_context(enabled=False),
            conversation_checkpointer(db, identity, token) as saver,
        ):
            graph = build_chat_graph(saver)
            graph.invoke(
                state,
                {"configurable": {"thread_id": identity}, "recursion_limit": 20},
                context=runtime,
                durability="sync",
            )
        return db.get(ChatMessage, assistant_id, populate_existing=True)
    except Exception as exc:
        failure = (
            model_failure_message(exc, "LLM")
            if isinstance(exc, ModelAPIError)
            else "回答生成失败，问题已保存，可以重试。"
        )
        logger.warning(
            "answer_failed conversation=%s request=%s code=%s type=%s",
            conversation_id,
            request_id,
            exc.code if isinstance(exc, ModelAPIError) else "workflow_error",
            type(exc).__name__,
        )
        db.rollback()
        conversation = db.get(Conversation, conversation_id, populate_existing=True)
        if not conversation:
            raise HTTPException(404, "对话不存在") from None
        assistant = db.get(ChatMessage, assistant_id, populate_existing=True)
        if assistant and assistant.status == "completed":
            return assistant
        if conversation and conversation.processing_token == token:
            if assistant:
                assistant.status = "failed"
                assistant.workflow_stage = "failed"
                assistant.error = exc.detail if isinstance(exc, HTTPException) else failure
            conversation.processing_token, conversation.processing_started_at = None, None
            db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(502, failure) from None


def update_stage(db, course_id, conversation_id, user_id, token, assistant_id, stage):
    conversation = owned_conversation(db, course_id, conversation_id, user_id, lock=True)
    if conversation.processing_token != token:
        raise HTTPException(409, "这次回答请求已失效，请查看最新对话")
    db.get(ChatMessage, assistant_id).workflow_stage = stage
    db.commit()


def remember_image_context(db, course_id, conversation_id, user_id, token, message_id, text):
    conversation = owned_conversation(db, course_id, conversation_id, user_id, lock=True)
    if conversation.processing_token != token:
        raise HTTPException(409, "这次回答请求已失效，请查看最新对话")
    db.get(ChatMessage, message_id).image_context = text
    db.commit()


def persist_answer(db, course_id, conversation_id, user_id, token, assistant_id, state):
    conversation = owned_conversation(db, course_id, conversation_id, user_id, lock=True)
    if conversation.processing_token != token:
        raise HTTPException(409, "这次回答请求已失效，请查看最新对话")
    versions = dict(
        db.execute(
            select(KnowledgePoint.id, KnowledgePoint.version)
            .where(
                KnowledgePoint.course_id == course_id,
                KnowledgePoint.status == "active",
                KnowledgePoint.id.in_([item["knowledge_id"] for item in state["items"]]),
            )
            .with_for_update()
        ).all()
    )
    if any(versions.get(item["knowledge_id"]) != item["version"] for item in state["items"]):
        raise HTTPException(409, "回答期间知识库已更新，请重试以使用最新内容")
    draft = AnswerDraft.model_validate(state["answer"])
    validate_answer(
        draft,
        state["items"],
        allow_conversation=state["retrieval_mode"] in {"conversation", "clarification", "image"},
    )
    assistant = db.get(ChatMessage, assistant_id)
    assistant.content, assistant.supplement = draft.answer, draft.supplement
    assistant.status, assistant.error, assistant.workflow_stage = "completed", None, "completed"
    assistant.citations = [item for item in state["items"] if item["key"] in draft.citations]
    assistant.warnings, assistant.retrieval_mode = state["warnings"], state["retrieval_mode"]
    if draft.status == "insufficient":
        assistant.warnings = [*assistant.warnings, "课程依据不足，未据此生成确定结论。"]
    assistant.model, assistant.input_tokens, assistant.output_tokens = (
        state["model"],
        state["input_tokens"],
        state["output_tokens"],
    )
    conversation.processing_token, conversation.processing_started_at, conversation.updated_at = (
        None,
        None,
        utcnow(),
    )
    db.commit()
