from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import undefer

from app.models import (
    Chapter,
    Document,
    ExerciseAsset,
    ExerciseLayout,
    ExtractionDraft,
    KnowledgePoint,
    PageExtraction,
    Workbook,
    WorkbookAsset,
)
from app.models.base import utcnow


def exercise_statement(course_id):
    return (
        select(ExtractionDraft, PageExtraction, Document, KnowledgePoint)
        .join(PageExtraction, PageExtraction.id == ExtractionDraft.extraction_id)
        .join(Document, Document.id == PageExtraction.document_id)
        .join(KnowledgePoint, KnowledgePoint.id == ExtractionDraft.knowledge_id)
        .where(
            Document.course_id == course_id,
            KnowledgePoint.course_id == course_id,
            KnowledgePoint.status == "active",
            PageExtraction.status == "completed",
            ExtractionDraft.kind.in_(["exercise", "worked_example"]),
            ExtractionDraft.status.in_(["imported", "accepted", "duplicate"]),
            ExtractionDraft.example.is_not(None),
        )
    )


def exercise_out(row, db=None):
    draft, page, document, point = row
    example = draft.example
    warnings = list(dict.fromkeys([*page.warnings, *draft.warnings, *example.get("warnings", [])]))
    if point.version > 1:
        warnings.append("知识库正文已修订；这里保留课件原始识别，请对照最新正文核对题目和答案。")
    warnings.extend(
        "公式识别不确定：$" + formula["latex"] + "$"
        for formula in example.get("formulas", [])
        if formula.get("uncertain")
    )
    result = {
        "draft_id": draft.id,
        "source_version": point.version,
        "title": draft.title,
        "question": example["question"],
        "answer": example.get("answer", ""),
        "solution": example.get("solution", ""),
        "kind": draft.kind,
        "document_id": document.id,
        "filename": document.filename,
        "page_number": page.page_number,
        "knowledge_id": point.id,
        "warnings": warnings,
        "layout_version": 0,
        "crop_status": "pending",
        "question_type": "other",
        "difficulty": "unknown",
        "knowledge_tags": [],
        "assets": [],
        "chapter": None,
        "asset_scope": "source",
    }
    if db is not None:
        chapter = db.scalar(
            select(Chapter).where(
                Chapter.document_id == document.id,
                Chapter.start_page <= page.page_number,
                Chapter.end_page >= page.page_number,
            )
        )
        if chapter:
            result["chapter"] = {"id": chapter.id, "title": chapter.title}
        layout = db.get(ExerciseLayout, draft.id)
        if layout:
            result.update(
                layout_version=layout.version,
                crop_status=layout.status,
                question_type=layout.question_type,
                difficulty=layout.difficulty,
                knowledge_tags=layout.knowledge_tags,
            )
            result["assets"] = [
                {"id": asset.id, "role": asset.role, "position": asset.position}
                for asset in db.scalars(
                    select(ExerciseAsset)
                    .where(
                        ExerciseAsset.draft_id == draft.id,
                        ExerciseAsset.layout_version == layout.version,
                    )
                    .order_by(ExerciseAsset.position)
                )
            ]
    return result


def find_workbook(db, course_id, workbook_id, *, lock=False):
    statement = select(Workbook).where(Workbook.id == workbook_id, Workbook.course_id == course_id)
    if lock:
        statement = statement.with_for_update()
    workbook = db.scalar(statement.execution_options(populate_existing=True))
    if not workbook:
        raise HTTPException(404, "做题本不存在")
    return workbook


def save_workbook(db, course_id, payload, workbook=None):
    if workbook:
        if workbook.version != payload.expected_version:
            raise HTTPException(409, "做题本已被更新，请刷新后再保存。")
    elif payload.expected_version != 0:
        raise HTTPException(409, "新做题本版本应为 0。")
    previous = (
        {item["draft_id"]: item for group in workbook.sections for item in group["items"]}
        if workbook
        else {}
    )
    requested = [item for group in payload.sections for item in group.items]
    fresh_ids = [
        item.draft_id
        for item in requested
        if item.draft_id not in previous
        or item.layout_version != previous[item.draft_id].get("layout_version", 0)
    ]
    rows = (
        db.execute(exercise_statement(course_id).where(ExtractionDraft.id.in_(fresh_ids))).all()
        if fresh_ids
        else []
    )
    available = {row[0].id: exercise_out(row, db) for row in rows}
    sections = []
    copy_items = []
    for group in payload.sections:
        items = []
        for item in group.items:
            # 已保存的快照独立于原课件，删除课件后仍可继续编辑和导出。
            fresh = item.draft_id in fresh_ids
            source = available.get(item.draft_id) if fresh else previous.get(item.draft_id)
            if source is None:
                raise HTTPException(404, "所选题目已删除或不属于这门课程，请重新选择。")
            if item.source_version != source["source_version"]:
                raise HTTPException(409, "所选题目的知识版本已变化，请重新载入题目后核对。")
            if item.layout_version != source.get("layout_version", 0):
                raise HTTPException(409, "题目裁片已变化，请重新载入后保存。")
            snapshot = {**source, **item.model_dump()}
            if fresh:
                copy_items.append(snapshot)
            items.append(snapshot)
        sections.append({"title": group.title, "items": items})
    workbook = workbook or Workbook(course_id=course_id, version=0)
    workbook.title, workbook.sections = payload.title, sections
    workbook.settings = payload.settings.model_dump()
    workbook.version += 1
    workbook.updated_at = utcnow()
    db.add(workbook)
    db.flush()
    preserved_ids = [
        asset["id"]
        for group in sections
        for item in group["items"]
        if item not in copy_items
        for asset in item.get("assets", [])
    ]
    total_bytes = db.scalar(
        select(func.coalesce(func.sum(func.length(WorkbookAsset.data)), 0)).where(
            WorkbookAsset.workbook_id == workbook.id, WorkbookAsset.id.in_(preserved_ids)
        )
    )
    for item in copy_items:
        original_ids = [asset["id"] for asset in item.get("assets", [])]
        assets = db.scalars(
            select(ExerciseAsset)
            .options(undefer(ExerciseAsset.data))
            .where(
                ExerciseAsset.id.in_(original_ids),
                ExerciseAsset.draft_id == item["draft_id"],
                ExerciseAsset.layout_version == item["layout_version"],
            )
        ).all()
        if len(assets) != len(original_ids):
            raise HTTPException(409, "题目裁片已变化，请重新载入后保存。")
        copied = []
        for asset in assets:
            total_bytes += len(asset.data)
            if total_bytes > 60 * 1024 * 1024:
                raise HTTPException(422, "做题本裁片总量过大，请拆分为多本。")
            snapshot_asset = WorkbookAsset(
                workbook_id=workbook.id,
                draft_id=item["draft_id"],
                role=asset.role,
                position=asset.position,
                data=asset.data,
            )
            db.add(snapshot_asset)
            db.flush()
            copied.append({"id": snapshot_asset.id, "role": asset.role, "position": asset.position})
        item["assets"] = sorted(copied, key=lambda asset: asset["position"])
        item["asset_scope"] = "workbook"
    used_ids = [
        asset["id"]
        for group in sections
        for item in group["items"]
        for asset in item.get("assets", [])
    ]
    db.execute(
        delete(WorkbookAsset).where(
            WorkbookAsset.workbook_id == workbook.id, WorkbookAsset.id.not_in(used_ids)
        )
    )
    # JSON 在 flush 后原地补入了图片快照 ID，需显式标记为脏。
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(workbook, "sections")
    db.commit()
    return workbook
