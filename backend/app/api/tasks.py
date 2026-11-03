from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.auth import DB, CurrentUser
from app.models import Course, Document, ProcessingTask
from app.schemas import TaskOut

router = APIRouter(tags=["tasks"])


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(user: CurrentUser, db: DB):
    rows = db.execute(
        select(ProcessingTask, Document.filename, Course.id, Course.name)
        .select_from(ProcessingTask)
        .join(Document, ProcessingTask.document_id == Document.id)
        .join(Course, Document.course_id == Course.id)
        .where(Course.user_id == user.id)
        .order_by(ProcessingTask.created_at.desc())
        .limit(100)
    ).all()
    return [
        TaskOut.model_validate(task).model_copy(
            update={
                "filename": filename,
                "course_id": course_id,
                "course_name": course_name,
            }
        )
        for task, filename, course_id, course_name in rows
    ]


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, user: CurrentUser, db: DB):
    row = db.execute(
        select(ProcessingTask, Document.filename, Course.id, Course.name)
        .select_from(ProcessingTask)
        .join(Document, ProcessingTask.document_id == Document.id)
        .join(Course, Document.course_id == Course.id)
        .where(ProcessingTask.id == task_id, Course.user_id == user.id)
    ).first()
    if not row:
        raise HTTPException(404, "处理记录不存在")
    task, filename, course_id, course_name = row
    return TaskOut.model_validate(task).model_copy(
        update={
            "filename": filename,
            "course_id": course_id,
            "course_name": course_name,
        }
    )
