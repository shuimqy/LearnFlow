from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.dependencies import owned_course, owned_document
from app.core.auth import DB, CurrentUser
from app.models import (
    KnowledgeChunk,
    KnowledgePoint,
    KnowledgeProposal,
    KnowledgeRevision,
    KnowledgeSource,
    SourceFragment,
)
from app.schemas.knowledge import (
    ConfirmInput,
    ExclusionInput,
    KnowledgeInput,
    KnowledgeOut,
    KnowledgeUpdate,
    PageOut,
    ProposalInput,
    ProposalOut,
    ProposalResolutionOut,
    RestoreInput,
    RevisionOut,
    SearchHit,
    SearchInput,
)
from app.services import knowledge as service
from app.services.sources import extract_page

router = APIRouter(tags=["knowledge"])


@router.post("/documents/{document_id}/pages/{page_number}/extract", response_model=PageOut)
def read_page(document_id: str, page_number: int, user: CurrentUser, db: DB):
    page = extract_page(db, owned_document(db, document_id, user.id), page_number)
    db.commit()
    return page


@router.get("/courses/{course_id}/knowledge", response_model=list[KnowledgeOut])
def list_knowledge(
    course_id: str,
    user: CurrentUser,
    db: DB,
    status: Literal["active", "archived"] = "active",
    q: str = Query(default="", max_length=200),
    chapter_id: str | None = None,
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    owned_course(db, course_id, user.id)
    statement = (
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.sources))
        .where(KnowledgePoint.course_id == course_id, KnowledgePoint.status == status)
    )
    if q.strip():
        statement = statement.where(
            KnowledgePoint.title.contains(q.strip(), autoescape=True)
            | KnowledgePoint.summary.contains(q.strip(), autoescape=True)
            | KnowledgePoint.content.contains(q.strip(), autoescape=True)
        )
    if chapter_id:
        from app.services.chapters import chapter_for

        chapter = chapter_for(db, course_id, chapter_id)
        statement = statement.where(
            KnowledgePoint.sources.any(
                (KnowledgeSource.document_id == chapter.document_id)
                & KnowledgeSource.page_number.between(chapter.start_page, chapter.end_page)
            )
        )
    return db.scalars(
        statement.order_by(KnowledgePoint.updated_at.desc(), KnowledgePoint.id)
        .offset(offset)
        .limit(limit)
    ).all()


@router.get("/courses/{course_id}/knowledge/stats")
def knowledge_stats(course_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    counts = dict(
        db.execute(
            select(KnowledgePoint.status, func.count(KnowledgePoint.id))
            .where(KnowledgePoint.course_id == course_id)
            .group_by(KnowledgePoint.status)
        ).all()
    )
    chunks = db.scalar(
        select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.course_id == course_id)
    )
    pending = db.scalar(
        select(func.count(KnowledgeProposal.id)).where(
            KnowledgeProposal.course_id == course_id, KnowledgeProposal.status == "pending"
        )
    )
    return {
        "active": counts.get("active", 0),
        "archived": counts.get("archived", 0),
        "chunks": chunks,
        "pending_proposals": pending,
        "search_mode": "text",
    }


@router.post("/courses/{course_id}/knowledge/search", response_model=list[SearchHit])
def search_knowledge(course_id: str, payload: SearchInput, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    rows = db.execute(
        select(KnowledgeChunk, KnowledgePoint)
        .join(KnowledgePoint, KnowledgeChunk.knowledge_id == KnowledgePoint.id)
        .options(selectinload(KnowledgePoint.sources))
        .where(
            KnowledgeChunk.course_id == course_id,
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.status == "active",
            KnowledgeChunk.version == KnowledgePoint.version,
            KnowledgeChunk.text.contains(payload.query, autoescape=True),
        )
        .order_by(KnowledgePoint.updated_at.desc(), KnowledgeChunk.position)
        .limit(payload.limit * 10)
    ).all()
    results, seen = [], set()
    for chunk, point in rows:
        if point.id in seen:
            continue
        seen.add(point.id)
        results.append(
            SearchHit(
                knowledge_id=point.id,
                title=point.title,
                version=point.version,
                text=chunk.text,
                sources=point.sources,
            )
        )
        if len(results) == payload.limit:
            break
    return results


@router.post("/courses/{course_id}/knowledge", response_model=KnowledgeOut, status_code=201)
def create_knowledge(course_id: str, payload: KnowledgeInput, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    return service.create_knowledge(db, course_id, user.id, payload)


@router.get("/courses/{course_id}/knowledge/{knowledge_id}", response_model=KnowledgeOut)
def get_knowledge(course_id: str, knowledge_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    return service.find_knowledge(db, course_id, knowledge_id)


@router.patch("/courses/{course_id}/knowledge/{knowledge_id}", response_model=KnowledgeOut)
def update_knowledge(
    course_id: str, knowledge_id: str, payload: KnowledgeUpdate, user: CurrentUser, db: DB
):
    owned_course(db, course_id, user.id)
    return service.update_knowledge(
        db, service.find_knowledge(db, course_id, knowledge_id), user.id, payload
    )


@router.delete("/courses/{course_id}/knowledge/{knowledge_id}", status_code=204)
def archive_knowledge(
    course_id: str,
    knowledge_id: str,
    user: CurrentUser,
    db: DB,
    expected_version: int = Query(ge=1),
):
    owned_course(db, course_id, user.id)
    point = service.find_knowledge(db, course_id, knowledge_id)
    service.check_version(point, expected_version)
    if point.status == "archived":
        raise HTTPException(409, "知识点已经归档")
    point.status = "archived"
    point.version += 1
    service.save_revision(db, point, user.id, "archive", "用户将知识点移出知识库")
    db.commit()


@router.get(
    "/courses/{course_id}/knowledge/{knowledge_id}/revisions", response_model=list[RevisionOut]
)
def list_revisions(course_id: str, knowledge_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    service.find_knowledge(db, course_id, knowledge_id)
    return db.scalars(
        select(KnowledgeRevision)
        .where(KnowledgeRevision.knowledge_id == knowledge_id)
        .order_by(KnowledgeRevision.version.desc())
    ).all()


@router.post("/courses/{course_id}/knowledge/{knowledge_id}/restore", response_model=KnowledgeOut)
def restore_knowledge(
    course_id: str, knowledge_id: str, payload: RestoreInput, user: CurrentUser, db: DB
):
    owned_course(db, course_id, user.id)
    return service.restore_knowledge(
        db, service.find_knowledge(db, course_id, knowledge_id), user.id, payload
    )


@router.get(
    "/courses/{course_id}/knowledge/{knowledge_id}/proposals", response_model=list[ProposalOut]
)
def list_proposals(course_id: str, knowledge_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    service.find_knowledge(db, course_id, knowledge_id)
    return db.scalars(
        select(KnowledgeProposal)
        .where(KnowledgeProposal.knowledge_id == knowledge_id)
        .order_by(KnowledgeProposal.created_at.desc())
    ).all()


@router.post(
    "/courses/{course_id}/knowledge/{knowledge_id}/proposals",
    response_model=ProposalOut,
    status_code=201,
)
def create_proposal(
    course_id: str, knowledge_id: str, payload: ProposalInput, user: CurrentUser, db: DB
):
    owned_course(db, course_id, user.id)
    return service.create_proposal(
        db, service.find_knowledge(db, course_id, knowledge_id), user.id, payload
    )


@router.post(
    "/courses/{course_id}/knowledge/{knowledge_id}/proposals/{proposal_id}/accept",
    response_model=ProposalResolutionOut,
)
def accept_proposal(
    course_id: str,
    knowledge_id: str,
    proposal_id: str,
    payload: ConfirmInput,
    user: CurrentUser,
    db: DB,
):
    owned_course(db, course_id, user.id)
    return service.resolve_proposal(
        db,
        service.find_knowledge(db, course_id, knowledge_id),
        proposal_id,
        user.id,
        True,
        payload.expected_version,
    )


@router.post(
    "/courses/{course_id}/knowledge/{knowledge_id}/proposals/{proposal_id}/reject",
    response_model=KnowledgeOut,
)
def reject_proposal(
    course_id: str,
    knowledge_id: str,
    proposal_id: str,
    payload: ConfirmInput,
    user: CurrentUser,
    db: DB,
):
    owned_course(db, course_id, user.id)
    return service.resolve_proposal(
        db,
        service.find_knowledge(db, course_id, knowledge_id),
        proposal_id,
        user.id,
        False,
        payload.expected_version,
    )


@router.delete(
    "/courses/{course_id}/knowledge/{knowledge_id}/proposals/{proposal_id}", status_code=204
)
def delete_proposal(course_id: str, knowledge_id: str, proposal_id: str, user: CurrentUser, db: DB):
    owned_course(db, course_id, user.id)
    service.delete_proposal(db, service.find_knowledge(db, course_id, knowledge_id), proposal_id)


@router.patch("/courses/{course_id}/source-fragments/{fragment_id}")
def exclude_fragment(
    course_id: str, fragment_id: str, payload: ExclusionInput, user: CurrentUser, db: DB
):
    owned_course(db, course_id, user.id)
    fragment = db.scalar(
        select(SourceFragment).where(
            SourceFragment.id == fragment_id, SourceFragment.course_id == course_id
        )
    )
    if not fragment:
        raise HTTPException(404, "原文片段不存在")
    if not payload.reason.strip():
        raise HTTPException(422, "请填写原因")
    fragment.excluded, fragment.exclusion_reason = payload.excluded, payload.reason.strip()
    db.commit()
    return {"id": fragment.id, "excluded": fragment.excluded, "reason": fragment.exclusion_reason}
