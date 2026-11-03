from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select

from app.api.dependencies import owned_course
from app.core.auth import DB, CurrentUser
from app.models import ChatImage, ChatMessage, Conversation, Course, Document, KnowledgePoint
from app.schemas.chat import (
    BranchInput,
    ConversationInput,
    ConversationOut,
    MessageOut,
    QuestionInput,
)
from app.services.account_models import is_configured, resolve_settings
from app.services.chat import ask_question, owned_conversation, processing, recover_interrupted
from app.services.chat_branches import create_branch
from app.services.chat_images import MAX_IMAGES, prepare_image
from app.services.vector_index import enqueue_course_index, index_status

router = APIRouter(tags=["chat"])


@router.get("/courses/{course_id}/retrieval/status")
def retrieval_status(course_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    settings = resolve_settings(db, user.id)
    return {
        **index_status(db, course_id),
        "llm_configured": is_configured(settings, "llm"),
        "llm_vision": settings.llm_vision,
    }


@router.post("/courses/{course_id}/retrieval/index", status_code=202)
def update_index(course_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    if not enqueue_course_index(db, course_id, force=True):
        raise HTTPException(503, "知识索引暂时无法启动，请检查模型配置和后台服务")
    return {"queued": True}


@router.get("/courses/{course_id}/conversations", response_model=list[ConversationOut])
def list_conversations(
    course_id: str, user: CurrentUser, db: DB, offset: int = Query(default=0, ge=0)
):
    owned_course(db, course_id, user.id)
    return db.scalars(
        select(Conversation)
        .where(Conversation.course_id == course_id, Conversation.parent_conversation_id.is_(None))
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .offset(offset)
        .limit(100)
    ).all()


@router.post("/courses/{course_id}/conversations", response_model=ConversationOut, status_code=201)
def create_conversation(course_id: str, payload: ConversationInput, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    conversation = Conversation(course_id=course_id, title=payload.title.strip() or "新对话")
    db.add(conversation)
    db.commit()
    return conversation


@router.get("/courses/{course_id}/conversations/{conversation_id}", response_model=ConversationOut)
def conversation_detail(course_id: str, conversation_id: str, user: CurrentUser, db: DB):
    return owned_conversation(db, course_id, conversation_id, user.id)


@router.get(
    "/courses/{course_id}/conversations/{conversation_id}/branches",
    response_model=list[ConversationOut],
)
def branches(course_id: str, conversation_id: str, user: CurrentUser, db: DB):
    owned_conversation(db, course_id, conversation_id, user.id)
    return db.scalars(
        select(Conversation)
        .where(
            Conversation.course_id == course_id,
            Conversation.parent_conversation_id == conversation_id,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(100)
    ).all()


@router.post(
    "/courses/{course_id}/conversations/{conversation_id}/branches",
    response_model=ConversationOut,
    status_code=201,
)
def start_branch(
    course_id: str, conversation_id: str, payload: BranchInput, user: CurrentUser, db: DB
):
    parent = owned_conversation(db, course_id, conversation_id, user.id, lock=True)
    return create_branch(db, parent, user.id, payload)


@router.delete("/courses/{course_id}/conversations/{conversation_id}", status_code=204)
def delete_conversation(course_id: str, conversation_id: str, user: CurrentUser, db: DB):
    conversation = owned_conversation(db, course_id, conversation_id, user.id, lock=True)
    recover_interrupted(db, conversation)
    if processing(conversation):
        raise HTTPException(409, "回答正在生成，完成后再删除对话")
    db.delete(conversation)
    db.commit()


def messages_out(db, course_id, messages):
    ids = {citation["knowledge_id"] for message in messages for citation in message.citations}
    documents = {
        source.get("document_id")
        for message in messages
        for citation in message.citations
        for source in citation["sources"]
    }
    points = {
        point.id: point
        for point in db.scalars(
            select(KnowledgePoint).where(
                KnowledgePoint.id.in_(ids), KnowledgePoint.course_id == course_id
            )
        )
    }
    available = set(
        db.scalars(
            select(Document.id).where(Document.id.in_(documents), Document.course_id == course_id)
        )
    )
    result = []
    for message in messages:
        citations = []
        for citation in message.citations:
            point = points.get(citation["knowledge_id"])
            citations.append(
                {
                    **citation,
                    "sources": [
                        {**source, "available": source.get("document_id") in available}
                        for source in citation["sources"]
                    ],
                    "current": bool(
                        point and point.status == "active" and point.version == citation["version"]
                    ),
                    "knowledge_status": point.status if point else "deleted",
                }
            )
        result.append(
            MessageOut.model_validate(message).model_copy(update={"citations": citations})
        )
    return result


@router.get(
    "/courses/{course_id}/conversations/{conversation_id}/messages", response_model=list[MessageOut]
)
def list_messages(
    course_id: str,
    conversation_id: str,
    user: CurrentUser,
    db: DB,
    before: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
):
    conversation = owned_conversation(db, course_id, conversation_id, user.id, lock=True)
    recover_interrupted(db, conversation)
    statement = select(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
    if before is not None:
        statement = statement.where(ChatMessage.sequence < before)
    rows = db.scalars(statement.order_by(ChatMessage.sequence.desc()).limit(limit)).all()
    return messages_out(db, course_id, list(reversed(rows)))


@router.post(
    "/courses/{course_id}/conversations/{conversation_id}/messages", response_model=MessageOut
)
def send_message(
    course_id: str, conversation_id: str, payload: QuestionInput, user: CurrentUser, db: DB
):
    return messages_out(
        db, course_id, [ask_question(db, course_id, conversation_id, user.id, payload)]
    )[0]


@router.post(
    "/courses/{course_id}/conversations/{conversation_id}/messages/with-images",
    response_model=MessageOut,
)
def send_image_message(
    course_id: str,
    conversation_id: str,
    user: CurrentUser,
    db: DB,
    request_id: Annotated[UUID, Form()],
    files: Annotated[list[UploadFile], File()],
    content: Annotated[str, Form(max_length=2000)] = "",
):
    owned_conversation(db, course_id, conversation_id, user.id)
    if not 1 <= len(files) <= MAX_IMAGES:
        raise HTTPException(422, "每条消息最多发送 4 张图片")
    images = [prepare_image(upload) for upload in files]
    payload = QuestionInput(content=content, request_id=request_id)
    return messages_out(
        db,
        course_id,
        [ask_question(db, course_id, conversation_id, user.id, payload, images=images)],
    )[0]


@router.get("/chat/images/{image_id}")
def image_content(image_id: str, user: CurrentUser, db: DB):
    image = db.scalar(
        select(ChatImage)
        .join(ChatMessage, ChatMessage.id == ChatImage.message_id)
        .join(Conversation, Conversation.id == ChatMessage.conversation_id)
        .join(Course, Course.id == Conversation.course_id)
        .where(ChatImage.id == image_id, Course.user_id == user.id)
    )
    if not image:
        raise HTTPException(404, "图片不存在")
    return Response(
        image.data, media_type=image.media_type, headers={"Content-Disposition": "inline"}
    )
