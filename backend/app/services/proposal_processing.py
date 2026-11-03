from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.model_runtime import use_model_settings
from app.models import KnowledgePoint, KnowledgeProposal
from app.models.base import new_id, utcnow
from app.schemas.knowledge import KnowledgeOut
from app.services.account_models import resolve_settings
from app.services.knowledge import apply_snapshot, check_version, save_revision, snapshot
from app.services.model_api import ModelAPIError
from app.services.proposal_review import read_review_sources, review_proposal


def find_proposal(db, point, proposal_id):
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
    return proposal


def process_proposal(db: Session, point, proposal_id: str, user_id: str, expected: int):
    db.refresh(point, with_for_update=True)
    check_version(point, expected)
    proposal = find_proposal(db, point, proposal_id)
    if (
        point.status != "active"
        or proposal.status != "pending"
        or proposal.base_version != expected
    ):
        raise HTTPException(409, "知识或建议已更新，请刷新后再处理")
    if proposal.processing:
        raise HTTPException(409, "模型正在处理这条建议，请稍后查看结果")
    token = new_id()
    current, proposed, reason = snapshot(point), deepcopy(proposal.proposed), proposal.reason
    proposal.processing_token, proposal.processing_started_at = token, utcnow()
    # 模型调用期间释放行锁，返回后重新校验知识版本和本次运行标识。
    db.commit()
    try:
        sources, images, tools, limited = read_review_sources(
            db, point.course_id, current["sources"] + proposed["sources"]
        )
        db.commit()
        model_settings = resolve_settings(db, user_id)
        db.commit()
        with use_model_settings(model_settings):
            response = review_proposal(current, proposed, reason, sources, images, limited)
    except ModelAPIError:
        proposal = find_proposal(db, point, proposal_id)
        if proposal.processing_token == token:
            proposal.processing_token, proposal.processing_started_at = None, None
            proposal.llm_review = {
                "outcome": "error",
                "applied": False,
                "message": "模型处理失败或返回不完整，知识未修改，可以重试。",
                "processed_at": utcnow().isoformat(),
                "base_version": expected,
            }
            db.commit()
        raise HTTPException(502, "模型处理失败或返回不完整，知识未修改，可以重试。") from None
    except Exception:
        db.rollback()
        proposal = find_proposal(db, point, proposal_id)
        if proposal.processing_token == token:
            proposal.processing_token = None
            db.commit()
        raise
    try:
        return finish_proposal(
            db,
            point,
            proposal_id,
            user_id,
            expected,
            token,
            current,
            proposed,
            reason,
            response,
            sources,
            tools,
        )
    except Exception as exc:
        db.rollback()
        proposal = db.get(KnowledgeProposal, proposal_id)
        if proposal and proposal.processing_token == token:
            proposal.processing_token, proposal.processing_started_at = None, None
            proposal.llm_review = {
                **response.parsed.model_dump(),
                "model": response.model,
                "outcome": "error",
                "applied": False,
                "message": "保存处理结果失败，知识未修改，请重试。",
                "processed_at": utcnow().isoformat(),
                "base_version": expected,
            }
            db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, "保存处理结果失败，请刷新查看知识版本和处理结果后重试。") from None


def finish_proposal(
    db,
    point,
    proposal_id,
    user_id,
    expected,
    token,
    current,
    proposed,
    reason,
    response,
    sources,
    tools,
):
    review = response.parsed
    point = db.scalar(
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.sources))
        .where(KnowledgePoint.id == point.id, KnowledgePoint.course_id == point.course_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not point:
        raise HTTPException(404, "知识点已被删除，本次未写入")
    proposal = find_proposal(db, point, proposal_id)
    if proposal.processing_token != token:
        raise HTTPException(409, "这次模型处理已失效，请刷新查看最新结果")
    report = {
        **review.model_dump(),
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "base_version": expected,
        "applied": False,
        "applied_version": None,
        "processed_at": utcnow().isoformat(),
        "sources": [
            {key: value for key, value in source.items() if key != "text"} for source in sources
        ],
        "tools": tools,
    }
    if point.version != expected or point.status != "active" or proposal.status != "pending":
        report.update(outcome="stale", message="知识已更新，模型意见已保留，本次未写入。")
        report["tools"].append(
            {"name": "save_knowledge_revision", "status": "skipped", "reason": "version_changed"}
        )
    elif review.verdict == "needs_evidence":
        report.update(
            outcome="needs_evidence",
            message="模型认为信息不足，知识未修改。请补充来源后重新提出建议。",
        )
    elif review.verdict == "reject":
        proposal.status, proposal.resolved_by, proposal.resolved_at = "rejected", user_id, utcnow()
        report.update(outcome="rejected", message="模型未采纳这条建议，知识未修改。")
    else:
        final = {
            "title": review.title,
            "summary": review.summary,
            "content": review.content,
            "sources": proposed["sources"],
        }
        proposal.status, proposal.resolved_by, proposal.resolved_at = "accepted", user_id, utcnow()
        unchanged = all(
            final[key] == current[key] for key in ("title", "summary", "content", "sources")
        )
        if unchanged:
            report.update(outcome="unchanged", message="模型处理后的内容与当前版本一致，无需修改。")
        else:
            apply_snapshot(db, point, final)
            save_revision(
                db,
                point,
                user_id,
                "correction",
                f"模型处理修改建议：{reason}\n模型意见：{review.opinion}",
                proposal.id,
            )
            report.update(
                outcome="applied",
                applied=True,
                applied_version=point.version,
                message=f"模型处理完成，已保存第 {point.version} 版并更新检索内容。",
            )
            report["tools"].append(
                {"name": "save_knowledge_revision", "status": "applied", "version": point.version}
            )
    proposal.processing_token, proposal.processing_started_at = None, None
    proposal.llm_review = report
    db.commit()
    return {**KnowledgeOut.model_validate(point).model_dump(), "processing": report}
