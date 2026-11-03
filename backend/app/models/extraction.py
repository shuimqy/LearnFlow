from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import new_id, utcnow


class PageExtraction(Base):
    __tablename__ = "page_extractions"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    transcript: Mapped[str] = mapped_column(Text, default="")
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtractionDraft(Base):
    __tablename__ = "extraction_drafts"
    __table_args__ = (UniqueConstraint("extraction_id", "position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    extraction_id: Mapped[str] = mapped_column(
        ForeignKey("page_extractions.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24), default="knowledge")
    example: Mapped[dict | None] = mapped_column(JSON)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    formulas: Mapped[list] = mapped_column(JSON)
    warnings: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    knowledge_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
