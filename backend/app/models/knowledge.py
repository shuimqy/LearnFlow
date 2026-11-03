from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import new_id, utcnow


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24))
    parser_version: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceFragment(Base):
    __tablename__ = "source_fragments"
    __table_args__ = (UniqueConstraint("page_id", "char_start", "char_end"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[str] = mapped_column(ForeignKey("document_pages.id", ondelete="CASCADE"))
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sources: Mapped[list["KnowledgeSource"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="KnowledgeSource.position"
    )
    __mapper_args__: ClassVar[dict] = {"version_id_col": version, "version_id_generator": False}


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    fragment_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_fragments.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(String(255))
    page_number: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)


class KnowledgeRevision(Base):
    __tablename__ = "knowledge_revisions"
    __table_args__ = (UniqueConstraint("knowledge_id", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    operation: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    confirmed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    proposal_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("knowledge_id", "version", "position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector().with_variant(JSON(), "sqlite"))
    embedding_status: Mapped[str] = mapped_column(String(16), default="pending")
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    embedding_fingerprint: Mapped[str | None] = mapped_column(String(64))
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer)
    embedding_error: Mapped[str | None] = mapped_column(String(255))
    embedding_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeProposal(Base):
    __tablename__ = "knowledge_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"))
    base_version: Mapped[int] = mapped_column(Integer)
    proposed: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_token: Mapped[str | None] = mapped_column(String(36))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    llm_review: Mapped[dict | None] = mapped_column(JSON)

    @property
    def processing(self) -> bool:
        if not self.processing_token or not self.processing_started_at:
            return False
        return utcnow() - self.processing_started_at.replace(tzinfo=UTC) < timedelta(minutes=5)
