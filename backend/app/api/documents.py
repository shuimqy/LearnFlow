from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.dependencies import owned_course, owned_document
from app.core.auth import DB, CurrentUser
from app.core.config import get_settings
from app.models import Document, ProcessingTask
from app.schemas import DocumentOut, ExerciseMode
from app.services.extraction_queue import submit_extraction
from app.services.storage import remove_file, save_pdf, storage_file

router = APIRouter(tags=["documents"])


@router.get("/courses/{course_id}/documents", response_model=list[DocumentOut])
def list_documents(course_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    return db.scalars(
        select(Document)
        .options(selectinload(Document.task))
        .where(Document.course_id == course_id)
        .order_by(Document.created_at.desc(), Document.id)
    ).all()


@router.post("/courses/{course_id}/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    course_id: str,
    user: CurrentUser,
    db: DB,
    file: Annotated[UploadFile, File()],
    exercise_mode: Annotated[ExerciseMode, Form()] = "both",
):
    course = owned_course(db, course_id, user.id)
    key, size, pages, filename = save_pdf(file)
    document = Document(
        course_id=course_id,
        filename=filename,
        storage_key=key,
        size_bytes=size,
        page_count=pages,
        exercise_mode=exercise_mode,
    )
    document.task = ProcessingTask(status="pending", stage="awaiting_extraction")
    try:
        db.add(document)
        course.updated_at = datetime.now(UTC)
        db.commit()
    except Exception:
        db.rollback()
        remove_file(key)
        raise
    if get_settings().extraction_auto_start:
        submit_extraction(db, document)
    return document


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: str, user: CurrentUser, db: DB):
    document = owned_document(db, document_id, user.id)
    path = storage_file(document.storage_key)
    if not path.is_file():
        raise HTTPException(404, "原始文件已丢失，请重新上传")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=document.filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str, user: CurrentUser, db: DB):
    document = owned_document(db, document_id, user.id)
    key = document.storage_key
    course = owned_course(db, document.course_id, user.id)
    course.updated_at = datetime.now(UTC)
    db.delete(document)
    db.commit()
    remove_file(key)
