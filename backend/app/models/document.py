from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import new_id, utcnow

if TYPE_CHECKING:
    from app.models.task import ProcessingTask


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int] = mapped_column(Integer)
    exercise_mode: Mapped[str] = mapped_column(String(16), default="both")
    status: Mapped[str] = mapped_column(String(24), default="uploaded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    task: Mapped["ProcessingTask"] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )
