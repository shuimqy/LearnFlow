from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select

from app.api.dependencies import owned_document
from app.core.auth import DB, CurrentUser
from app.models import ExtractionDraft, PageExtraction
from app.schemas.extraction import AcceptDraft, DraftOut, ExtractionPageOut
from app.schemas.knowledge import KnowledgeOut
from app.schemas.task import TaskOut
from app.services.extraction import accept_draft
from app.services.extraction_queue import reconcile_task, submit_extraction
from app.services.pdf_pages import render_page

router = APIRouter(tags=["extraction"])


@router.post("/documents/{document_id}/extraction", response_model=TaskOut, status_code=202)
def start_extraction(document_id: str, user: CurrentUser, db: DB):
    document = owned_document(db, document_id, user.id)
    reconcile_task(db, document.task)
    return submit_extraction(db, document)


@router.get("/documents/{document_id}/extraction")
def extraction_status(document_id: str, user: CurrentUser, db: DB):
    document = owned_document(db, document_id, user.id)
    reconcile_task(db, document.task)
    rows = db.scalars(
        select(PageExtraction)
        .where(PageExtraction.document_id == document.id)
        .order_by(PageExtraction.page_number)
    ).all()
    counts = db.execute(
        select(ExtractionDraft.extraction_id, ExtractionDraft.status, func.count())
        .join(PageExtraction)
        .where(PageExtraction.document_id == document.id)
        .group_by(ExtractionDraft.extraction_id, ExtractionDraft.status)
    ).all()
    by_page = {}
    for page_id, status, count in counts:
        by_page.setdefault(page_id, {})[status] = count
    return {
        "document_id": document.id,
        "page_count": document.page_count,
        "task": TaskOut.model_validate(document.task),
        "pages": [
            {
                "id": page.id,
                "page_number": page.page_number,
                "status": page.status,
                "warnings": page.warnings,
                "error": page.error,
                "counts": by_page.get(page.id, {}),
            }
            for page in rows
        ],
    }


@router.get(
    "/documents/{document_id}/extraction/pages/{page_number}", response_model=ExtractionPageOut
)
def extraction_page(document_id: str, page_number: int, user: CurrentUser, db: DB):
    owned_document(db, document_id, user.id)
    page = db.scalar(
        select(PageExtraction).where(
            PageExtraction.document_id == document_id, PageExtraction.page_number == page_number
        )
    )
    if not page:
        raise HTTPException(404, "该页尚未开始处理")
    drafts = db.scalars(
        select(ExtractionDraft)
        .where(ExtractionDraft.extraction_id == page.id)
        .order_by(ExtractionDraft.position)
    ).all()
    return ExtractionPageOut.model_validate(
        {
            **{
                name: getattr(page, name)
                for name in ExtractionPageOut.model_fields
                if name != "drafts"
            },
            "drafts": [DraftOut.model_validate(draft) for draft in drafts],
        }
    )


@router.get("/documents/{document_id}/pages/{page_number}/image")
def page_image(document_id: str, page_number: int, user: CurrentUser, db: DB):
    document = owned_document(db, document_id, user.id)
    return Response(
        render_page(document, page_number),
        media_type="image/png",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post(
    "/documents/{document_id}/extraction/drafts/{draft_id}/accept", response_model=KnowledgeOut
)
def confirm_draft(document_id: str, draft_id: str, payload: AcceptDraft, user: CurrentUser, db: DB):
    return accept_draft(db, owned_document(db, document_id, user.id), draft_id, user.id, payload)


@router.post("/documents/{document_id}/extraction/drafts/{draft_id}/discard", status_code=204)
def discard_draft(document_id: str, draft_id: str, user: CurrentUser, db: DB):
    owned_document(db, document_id, user.id)
    draft = db.scalar(
        select(ExtractionDraft)
        .join(PageExtraction)
        .where(ExtractionDraft.id == draft_id, PageExtraction.document_id == document_id)
        .with_for_update(of=ExtractionDraft)
    )
    if not draft:
        raise HTTPException(404, "提取草稿不存在")
    if draft.status != "pending":
        raise HTTPException(409, "这条草稿已经处理")
    draft.status = "discarded"
    db.commit()
