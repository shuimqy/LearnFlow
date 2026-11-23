import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import UUID
from zipfile import BadZipFile
from zlib import error as CompressionError

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.api.dependencies import owned_course
from app.core.auth import DB, CurrentUser
from app.models import Course, Document
from app.schemas import CourseInput, CourseOut
from app.services.course_import import import_course_package
from app.services.course_package import export_course_package, validate_course_package
from app.services.query_embeddings import clear_query_cache
from app.services.storage import remove_file

router = APIRouter(tags=["courses"])


def course_output(db, course: Course) -> CourseOut:
    count = db.scalar(select(func.count(Document.id)).where(Document.course_id == course.id))
    return CourseOut.model_validate(course).model_copy(update={"document_count": count})


@router.get("/courses", response_model=list[CourseOut])
def list_courses(user: CurrentUser, db: DB):
    counts = (
        select(Document.course_id, func.count(Document.id).label("total"))
        .group_by(Document.course_id)
        .subquery()
    )
    rows = db.execute(
        select(Course, func.coalesce(counts.c.total, 0))
        .outerjoin(counts, counts.c.course_id == Course.id)
        .where(Course.user_id == user.id)
        .order_by(Course.updated_at.desc(), Course.id)
    ).all()
    return [
        CourseOut.model_validate(course).model_copy(update={"document_count": count})
        for course, count in rows
    ]


@router.post("/courses", response_model=CourseOut, status_code=201)
def create_course(payload: CourseInput, user: CurrentUser, db: DB):
    course = Course(user_id=user.id, **payload.model_dump())
    db.add(course)
    db.commit()
    return course


@router.post("/courses/import", response_model=CourseOut, status_code=201)
def import_course(
    user: CurrentUser,
    db: DB,
    file: Annotated[UploadFile, File()],
    request_id: Annotated[UUID | None, Form()] = None,
):
    try:
        course = import_course_package(db, user.id, file.file, request_id)
    except (BadZipFile, KeyError, ValueError, RuntimeError, CompressionError, DataError):
        raise HTTPException(
            422, "课程包无效或格式版本不受支持，请选择 LearnFlow 导出的 ZIP。"
        ) from None
    except OSError:
        raise HTTPException(503, "无法保存课程资料，请检查本机文件存储是否可用。") from None
    return course_output(db, course)


@router.get("/courses/{course_id}/export")
def export_course(course_id: str, user: CurrentUser, db: DB):
    course = owned_course(db, course_id, user.id)
    folder = TemporaryDirectory(prefix="learnflow-course-export-")
    try:
        path = Path(folder.name) / "course.zip"
        with Session(bind=db.get_bind()) as snapshot:
            if snapshot.get_bind().dialect.name == "postgresql":
                snapshot.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            export_course_package(snapshot, course.id, user.id, path)
        validate_course_package(path)
    except (OSError, ValueError, BadZipFile, KeyError):
        folder.cleanup()
        raise HTTPException(409, "课程资料暂时无法导出，请检查课件文件和引用是否完整。") from None
    except BaseException:
        folder.cleanup()
        raise
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", course.name).strip(" .") or "课程"
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{name}.learnflow.zip",
        background=BackgroundTask(folder.cleanup),
    )


@router.get("/courses/{course_id}", response_model=CourseOut)
def get_course(course_id: str, user: CurrentUser, db: DB):
    return course_output(db, owned_course(db, course_id, user.id))


@router.patch("/courses/{course_id}", response_model=CourseOut)
def update_course(course_id: str, payload: CourseInput, user: CurrentUser, db: DB):
    course = owned_course(db, course_id, user.id)
    for key, value in payload.model_dump().items():
        setattr(course, key, value)
    db.commit()
    return course_output(db, course)


@router.delete("/courses/{course_id}", status_code=204)
def delete_course(course_id: str, user: CurrentUser, db: DB):
    course = owned_course(db, course_id, user.id)
    keys = list(db.scalars(select(Document.storage_key).where(Document.course_id == course_id)))
    db.delete(course)
    db.commit()
    clear_query_cache(user.id, course_id)
    for key in keys:
        remove_file(key)
