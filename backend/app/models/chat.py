from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import new_id, utcnow


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    parent_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    parent_message_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "chat_messages.id", ondelete="CASCADE", use_alter=True, name="fk_branch_parent_message"
        )
    )
    branch_request_id: Mapped[str | None] = mapped_column(String(36))
    anchor_text: Mapped[str] = mapped_column(Text, default="")
    context_mode: Mapped[str | None] = mapped_column(String(16))
    context_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    processing_token: Mapped[str | None] = mapped_column(String(36))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def source_question(self):
        return self.context_snapshot.get("original_question", "")

    @property
    def context_truncated(self):
        return self.context_snapshot.get("truncated", False)

    @property
    def source_images(self):
        return self.context_snapshot.get("source_images", [])

    __table_args__ = (UniqueConstraint("parent_conversation_id", "branch_request_id"),)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence"),
        UniqueConstraint("conversation_id", "request_id", "role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    supplement: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="completed")
    workflow_stage: Mapped[str | None] = mapped_column(String(24))
    citations: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    retrieval_mode: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    image_context: Mapped[str] = mapped_column(Text, default="")
    images: Mapped[list["ChatImage"]] = relationship(
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        order_by="ChatImage.position",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatImage(Base):
    __tablename__ = "chat_images"
    __table_args__ = (UniqueConstraint("message_id", "position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(32))
    size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
