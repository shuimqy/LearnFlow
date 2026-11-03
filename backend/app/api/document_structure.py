from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import owned_course, owned_document
from app.core.auth import DB, CurrentUser
from app.models import ExerciseAsset, ExtractionDraft, WorkbookAsset
from app.schemas.document_structure import ChapterUpdate, LayoutInput
from app.services.chapters import chapter_list, save_chapters
from app.services.document_organization import structure_state, submit_organization
from app.services.exercise_layouts import layout_out, owned_exercise, save_layout
from app.services.workbooks import exercise_out, exercise_statement, find_workbook

router = APIRouter(tags=["document-structure"])


class StartOrganization(BaseModel):
    expected_version: int = Field(ge=0)


@router.get("/courses/{course_id}/chapters")
def course_chapters(course_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    return chapter_list(db, course_id)


@router.get("/documents/{document_id}/structure")
def get_structure(document_id: str, user: CurrentUser, db: DB):
    document = owned_document(db, document_id, user.id)
    return {
        **structure_state(db, document_id),
        "chapters": [
            item
            for item in chapter_list(db, document.course_id)
            if item["document_id"] == document_id
        ],
    }


@router.post("/documents/{document_id}/structure", status_code=202)
def start_structure(document_id: str, payload: StartOrganization, user: CurrentUser, db: DB):
    return submit_organization(
        db, owned_document(db, document_id, user.id), payload.expected_version
    )


@router.put("/documents/{document_id}/chapters")
def edit_chapters(document_id: str, payload: ChapterUpdate, user: CurrentUser, db: DB):
    document = owned_document(db, document_id, user.id)
    save_chapters(db, document, payload)
    return get_structure(document_id, user, db)


@router.get("/courses/{course_id}/exercises/{draft_id}/layout")
def get_layout(course_id: str, draft_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    owned_exercise(db, course_id, draft_id)
    return layout_out(db, draft_id)


@router.get("/courses/{course_id}/exercises/{draft_id}")
def get_exercise(course_id: str, draft_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    row = db.execute(exercise_statement(course_id).where(ExtractionDraft.id == draft_id)).first()
    if not row:
        raise HTTPException(404, "题目已删除或归档")
    return exercise_out(row, db)


@router.put("/courses/{course_id}/exercises/{draft_id}/layout")
def update_layout(course_id: str, draft_id: str, payload: LayoutInput, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    return save_layout(db, course_id, draft_id, payload)


@router.get("/courses/{course_id}/exercises/{draft_id}/assets/{asset_id}")
def exercise_asset(course_id: str, draft_id: str, asset_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    owned_exercise(db, course_id, draft_id)
    asset = db.scalar(
        select(ExerciseAsset).where(
            ExerciseAsset.id == asset_id, ExerciseAsset.draft_id == draft_id
        )
    )
    if not asset:
        raise HTTPException(404, "裁片不存在")
    return Response(asset.data, media_type="image/png")


@router.get("/courses/{course_id}/workbooks/{workbook_id}/assets/{asset_id}")
def workbook_asset(course_id: str, workbook_id: str, asset_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    find_workbook(db, course_id, workbook_id)
    asset = db.scalar(
        select(WorkbookAsset).where(
            WorkbookAsset.id == asset_id, WorkbookAsset.workbook_id == workbook_id
        )
    )
    if not asset:
        raise HTTPException(404, "裁片不存在")
    return Response(asset.data, media_type="image/png")
