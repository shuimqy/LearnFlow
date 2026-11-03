from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import new_id, utcnow


class DocumentStructure(Base):
    __tablename__ = "document_structures"

    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    run_id: Mapped[str | None] = mapped_column(String(36))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    start_page: Mapped[int] = mapped_column(Integer)
    end_page: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(24), default="manual")


class ExerciseLayout(Base):
    __tablename__ = "exercise_layouts"

    draft_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_drafts.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="suggested")
    regions: Mapped[list] = mapped_column(JSON, default=list)
    question_type: Mapped[str] = mapped_column(String(24), default="other")
    difficulty: Mapped[str] = mapped_column(String(24), default="unknown")
    knowledge_tags: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExerciseAsset(Base):
    __tablename__ = "exercise_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    draft_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_drafts.id", ondelete="CASCADE"), index=True
    )
    layout_version: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(Integer)
    page_number: Mapped[int] = mapped_column(Integer)
    bbox: Mapped[list] = mapped_column(JSON)
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class WorkbookAsset(Base):
    __tablename__ = "workbook_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workbook_id: Mapped[str] = mapped_column(
        ForeignKey("workbooks.id", ondelete="CASCADE"), index=True
    )
    draft_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
