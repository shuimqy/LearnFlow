from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, Document


def owned_course(db: Session, course_id: str, user_id: str) -> Course:
    course = db.scalar(select(Course).where(Course.id == course_id, Course.user_id == user_id))
    if not course:
        raise HTTPException(404, "课程不存在")
    return course


def owned_document(db: Session, document_id: str, user_id: str) -> Document:
    document = db.scalar(
        select(Document).join(Course).where(Document.id == document_id, Course.user_id == user_id)
    )
    if not document:
        raise HTTPException(404, "文件不存在")
    return document
