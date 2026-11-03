from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.dependencies import owned_course
from app.core.auth import DB, CurrentUser
from app.models import Course, Document
from app.schemas import CourseInput, CourseOut
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
