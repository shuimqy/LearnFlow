from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import new_id, utcnow


class ModelProfile(Base):
    __tablename__ = "model_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    config: Mapped[dict] = mapped_column(JSON)
    encrypted_key: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountModels(Base):
    __tablename__ = "account_models"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    llm_id: Mapped[str | None] = mapped_column(ForeignKey("model_profiles.id", ondelete="SET NULL"))
    embedding_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_profiles.id", ondelete="SET NULL")
    )
    pending_embedding_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_profiles.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, default=1)


class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("model_profiles.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector().with_variant(JSON(), "sqlite"))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error: Mapped[str | None] = mapped_column(String(255))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
