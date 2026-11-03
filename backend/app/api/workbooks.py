from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import func, select

from app.api.dependencies import owned_course, owned_document
from app.core.auth import DB, CurrentUser
from app.core.model_runtime import use_model_settings
from app.models import Document, ExtractionDraft, PageExtraction, Workbook
from app.models.base import utcnow
from app.schemas.workbook import WorkbookInput, WorkbookOut, WorkbookRename, WorkbookSummary
from app.schemas.workbook_assembly import AssemblyInput
from app.services.account_models import resolve_settings
from app.services.chapters import chapter_for, chapter_list
from app.services.workbook_assembly import assemble_workbook
from app.services.workbook_images import attach_workbook_images
from app.services.workbook_pdf import render_workbook_pdf
from app.services.workbook_scope import filter_scope, validate_sources
from app.services.workbooks import exercise_out, exercise_statement, find_workbook, save_workbook

router = APIRouter(prefix="/courses/{course_id}", tags=["workbooks"])


@router.get("/exercises")
def exercises(
    course_id: str,
    user: CurrentUser,
    db: DB,
    document_id: str | None = None,
    chapter_id: str | None = None,
    document_ids: Annotated[list[str] | None, Query(min_length=1, max_length=100)] = None,
    chapter_ids: Annotated[list[str] | None, Query(max_length=100)] = None,
    page_from: int | None = Query(default=None, ge=1),
    page_to: int | None = Query(default=None, ge=1),
    kind: Literal["exercise", "worked_example"] | None = None,
    query: str = Query(default="", max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
):
    owned_course(db, course_id, user.id)
    validate_sources(db, course_id, document_ids)
    if document_id:
        document = owned_document(db, document_id, user.id)
        if document.course_id != course_id:
            raise HTTPException(404, "文件不属于这门课程。")
    statement = exercise_statement(course_id)
    if chapter_id:
        chapter = chapter_for(db, course_id, chapter_id)
        statement = statement.where(
            Document.id == chapter.document_id,
            PageExtraction.page_number.between(chapter.start_page, chapter.end_page),
        )
    if document_id:
        statement = statement.where(Document.id == document_id)
    chapters = chapter_list(db, course_id) if chapter_ids else []
    if document_ids is not None:
        chapters = [chapter for chapter in chapters if chapter["document_id"] in document_ids]
    statement = filter_scope(
        statement, chapters, document_ids, chapter_ids or [], page_from, page_to
    )
    if kind:
        statement = statement.where(ExtractionDraft.kind == kind)
    if query.strip():
        statement = statement.where(ExtractionDraft.title.contains(query.strip(), autoescape=True))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.execute(
        statement.order_by(
            Document.created_at, Document.id, PageExtraction.page_number, ExtractionDraft.position
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return {"total": total, "items": [exercise_out(row, db) for row in rows]}


@router.get("/workbooks", response_model=list[WorkbookSummary])
def list_workbooks(course_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    return db.scalars(
        select(Workbook).where(Workbook.course_id == course_id).order_by(Workbook.updated_at.desc())
    ).all()


@router.post("/workbooks/assemble")
def automatic_workbook(course_id: str, payload: AssemblyInput, user: CurrentUser, db: DB):
    course = owned_course(db, course_id, user.id)
    settings = resolve_settings(db, user.id)
    with use_model_settings(settings):
        return assemble_workbook(db, course, payload)


@router.post("/workbooks", response_model=WorkbookOut, status_code=201)
def create_workbook(course_id: str, payload: WorkbookInput, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    return save_workbook(db, course_id, payload)


@router.get("/workbooks/{workbook_id}", response_model=WorkbookOut)
def get_workbook(course_id: str, workbook_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    return find_workbook(db, course_id, workbook_id)


@router.put("/workbooks/{workbook_id}", response_model=WorkbookOut)
def update_workbook(
    course_id: str, workbook_id: str, payload: WorkbookInput, user: CurrentUser, db: DB
):
    owned_course(db, course_id, user.id)
    return save_workbook(
        db, course_id, payload, find_workbook(db, course_id, workbook_id, lock=True)
    )


@router.delete("/workbooks/{workbook_id}", status_code=204)
def delete_workbook(course_id: str, workbook_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    db.delete(find_workbook(db, course_id, workbook_id, lock=True))
    db.commit()


@router.patch("/workbooks/{workbook_id}/title", response_model=WorkbookOut)
def rename_workbook(
    course_id: str, workbook_id: str, payload: WorkbookRename, user: CurrentUser, db: DB
):
    owned_course(db, course_id, user.id)
    workbook = find_workbook(db, course_id, workbook_id, lock=True)
    if workbook.version != payload.expected_version:
        raise HTTPException(409, "做题本已被更新，请重新打开后再修改名称。")
    workbook.title = payload.title
    workbook.version += 1
    workbook.updated_at = utcnow()
    db.commit()
    return workbook


@router.get("/workbooks/{workbook_id}/pdf")
def export_pdf(
    course_id: str, workbook_id: str, user: CurrentUser, db: DB, version: int = Query(ge=1)
):
    course = owned_course(db, course_id, user.id)
    workbook = find_workbook(db, course_id, workbook_id)
    if workbook.version != version:
        raise HTTPException(409, "做题本已变更，请载入最新版本后导出。")
    snapshot = {
        "title": workbook.title,
        "course_name": course.name,
        "sections": workbook.sections,
        "settings": workbook.settings,
    }
    filename = quote(workbook.title + ".pdf", safe="")
    snapshot = attach_workbook_images(db, workbook, snapshot)
    db.commit()
    return Response(
        render_workbook_pdf(snapshot),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=workbook.pdf; filename*=UTF-8''{filename}",
            "Cache-Control": "private, no-store",
        },
    )
