from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.models import Course, KnowledgePoint, KnowledgeProposal, KnowledgeRevision
from app.models.base import utcnow
from app.schemas.knowledge import KnowledgeInput
from app.services.knowledge_index import rebuild_chunks
from app.services.sources import resolve_sources, restore_sources, source_snapshot


def find_knowledge(db: Session, course_id: str, knowledge_id: str) -> KnowledgePoint:
    point = db.scalar(
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.sources))
        .where(KnowledgePoint.id == knowledge_id, KnowledgePoint.course_id == course_id)
    )
    if not point:
        raise HTTPException(404, "知识点不存在")
    return point


def check_version(point: KnowledgePoint, expected: int):
    if point.version != expected:
        raise HTTPException(409, "知识点已被更新，请刷新后比较最新内容再修改")


def snapshot(point: KnowledgePoint) -> dict:
    return {
        "title": point.title,
        "summary": point.summary,
        "content": point.content,
        "status": point.status,
        "sources": source_snapshot(point.sources),
    }


def save_revision(
    db: Session,
    point: KnowledgePoint,
    user_id: str,
    operation: str,
    reason: str,
    proposal_id: str | None = None,
):
    if not reason.strip():
        raise HTTPException(422, "请填写修改原因")
    point.updated_at = utcnow()
    point.updated_by = user_id
    db.flush()
    db.add(
        KnowledgeRevision(
            knowledge_id=point.id,
            version=point.version,
            snapshot=snapshot(point),
            operation=operation,
            reason=reason.strip(),
            confirmed_by=user_id,
            proposal_id=proposal_id,
        )
    )
    rebuild_chunks(db, point)
    db.execute(
        update(KnowledgeProposal)
        .where(
            KnowledgeProposal.knowledge_id == point.id,
            KnowledgeProposal.status == "pending",
            KnowledgeProposal.base_version < point.version,
        )
        .values(status="superseded", resolved_at=utcnow())
    )
    course = db.get(Course, point.course_id)
    course.updated_at = utcnow()


def create_knowledge(db: Session, course_id: str, user_id: str, payload: KnowledgeInput):
    point = KnowledgePoint(
        course_id=course_id,
        title=payload.title,
        summary=payload.summary,
        content=payload.content,
        version=1,
        status="active",
        created_by=user_id,
        updated_by=user_id,
    )
    point.sources = resolve_sources(db, course_id, payload.sources)
    db.add(point)
    save_revision(db, point, user_id, "create", "创建知识点")
    db.commit()
    return point


def delete_proposal(db: Session, point: KnowledgePoint, proposal_id: str):
    db.refresh(point, with_for_update=True)
    proposal = db.scalar(
        select(KnowledgeProposal)
        .where(
            KnowledgeProposal.id == proposal_id,
            KnowledgeProposal.knowledge_id == point.id,
            KnowledgeProposal.course_id == point.course_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not proposal:
        raise HTTPException(404, "修改建议不存在")
    if proposal.processing:
        raise HTTPException(409, "模型正在处理这条建议，完成后再删除")
    db.delete(proposal)
    db.commit()


def update_knowledge(db: Session, point: KnowledgePoint, user_id: str, payload):
    check_version(point, payload.expected_version)
    if point.status != "active":
        raise HTTPException(409, "请先恢复已归档的知识点")
    sources = resolve_sources(db, point.course_id, payload.sources, point)
    point.title, point.summary, point.content = payload.title, payload.summary, payload.content
    point.sources = sources
    point.version += 1
    save_revision(db, point, user_id, "update", payload.reason)
    db.commit()
    return point


def restore_knowledge(db: Session, point: KnowledgePoint, user_id: str, payload):
    check_version(point, payload.expected_version)
    revision = db.scalar(
        select(KnowledgeRevision).where(
            KnowledgeRevision.id == payload.revision_id, KnowledgeRevision.knowledge_id == point.id
        )
    )
    if not revision:
        raise HTTPException(404, "修订版本不存在")
    apply_snapshot(db, point, revision.snapshot)
    save_revision(db, point, user_id, "restore", payload.reason)
    db.commit()
    return point


def apply_snapshot(db: Session, point: KnowledgePoint, saved: dict):
    point.title, point.summary, point.content = saved["title"], saved["summary"], saved["content"]
    point.sources = restore_sources(db, point.course_id, saved["sources"])
    point.status = "active"
    point.version += 1


def create_proposal(db: Session, point: KnowledgePoint, user_id: str, payload):
    check_version(point, payload.expected_version)
    if point.status != "active":
        raise HTTPException(409, "知识点已归档，无法提出修订")
    references = resolve_sources(db, point.course_id, payload.sources, point)
    proposal = KnowledgeProposal(
        course_id=point.course_id,
        knowledge_id=point.id,
        base_version=point.version,
        proposed={
            "title": payload.title,
            "summary": payload.summary,
            "content": payload.content,
            "sources": source_snapshot(references),
        },
        reason=payload.reason,
        created_by=user_id,
    )
    db.add(proposal)
    db.commit()
    return proposal


def resolve_proposal(
    db: Session, point: KnowledgePoint, proposal_id: str, user_id: str, accept: bool, expected: int
):
    if accept:
        from app.services.proposal_processing import process_proposal

        return process_proposal(db, point, proposal_id, user_id, expected)
    # 与普通修订保持相同的加锁顺序：知识点在前，建议在后。
    db.refresh(point, with_for_update=True)
    check_version(point, expected)
    proposal = db.scalar(
        select(KnowledgeProposal).where(
            KnowledgeProposal.id == proposal_id,
            KnowledgeProposal.knowledge_id == point.id,
            KnowledgeProposal.course_id == point.course_id,
        )
    )
    if not proposal:
        raise HTTPException(404, "修改建议不存在")
    if proposal.status != "pending":
        raise HTTPException(409, "该建议已处理或已过期，请刷新后查看")
    if proposal.processing:
        raise HTTPException(409, "模型正在处理这条建议，请稍后查看结果")
    if point.status != "active":
        raise HTTPException(409, "知识点已归档")
    result = db.execute(
        update(KnowledgeProposal)
        .where(KnowledgeProposal.id == proposal.id, KnowledgeProposal.status == "pending")
        .values(status="rejected", resolved_by=user_id, resolved_at=utcnow())
    )
    if result.rowcount != 1:
        raise HTTPException(409, "该建议已被处理，请刷新后查看")
    db.commit()
    return point
