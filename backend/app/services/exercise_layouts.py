import pymupdf
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.models import Document, ExerciseAsset, ExerciseLayout, ExtractionDraft, PageExtraction
from app.models.base import utcnow
from app.services.storage import storage_file


def owned_exercise(db, course_id, draft_id):
    row = db.execute(
        select(ExtractionDraft, PageExtraction, Document)
        .select_from(ExtractionDraft)
        .join(PageExtraction, PageExtraction.id == ExtractionDraft.extraction_id)
        .join(Document, Document.id == PageExtraction.document_id)
        .where(
            ExtractionDraft.id == draft_id,
            Document.course_id == course_id,
            ExtractionDraft.kind.in_(["exercise", "worked_example"]),
        )
    ).first()
    if not row:
        raise HTTPException(404, "题目不存在或不属于这门课程。")
    return row


def layout_out(db, draft_id):
    layout = db.get(ExerciseLayout, draft_id)
    return {
        "draft_id": draft_id,
        "version": layout.version if layout else 0,
        "status": layout.status if layout else "pending",
        "regions": layout.regions if layout else [],
        "question_type": layout.question_type if layout else "other",
        "difficulty": layout.difficulty if layout else "unknown",
        "knowledge_tags": layout.knowledge_tags if layout else [],
        "warnings": layout.warnings if layout else [],
    }


def crop_regions(document, regions):
    path = storage_file(document.storage_key)
    if not path.is_file():
        raise HTTPException(404, "原课件已丢失，无法裁切。")
    assets, total = [], 0
    try:
        with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as pdf:
            for region in regions:
                if region.page_number > len(pdf):
                    raise HTTPException(422, "裁片页码超出课件范围。")
                page = pdf[region.page_number - 1]
                x0, y0, x1, y1 = region.bbox
                # 在与网页预览相同的旋转坐标系裁切，裁片只保留可见像素。
                rect = pymupdf.Rect(
                    x0 * page.rect.width,
                    y0 * page.rect.height,
                    x1 * page.rect.width,
                    y1 * page.rect.height,
                )
                scale = min(3.0, 3000 / max(rect.width, rect.height))
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale),
                    clip=rect,
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                )
                data = pixmap.tobytes("png")
                total += len(data)
                if total > 20 * 1024 * 1024:
                    raise HTTPException(422, "裁片总量超过 20 MB，请缩小范围。")
                assets.append(data)
    except (pymupdf.FileDataError, RuntimeError, IndexError) as exc:
        raise HTTPException(422, "无法裁切原页，请检查课件和框选范围。") from exc
    return assets


def save_layout(db, course_id, draft_id, payload):
    _draft, _page, document = owned_exercise(db, course_id, draft_id)
    db.scalar(select(ExtractionDraft).where(ExtractionDraft.id == draft_id).with_for_update())
    layout = db.get(ExerciseLayout, draft_id)
    if (layout.version if layout else 0) != payload.expected_version:
        raise HTTPException(409, "题目裁片已更新，请重新打开后核对。")
    if any(region.page_number > document.page_count for region in payload.regions):
        raise HTTPException(422, "裁片页码超出课件范围。")
    if payload.confirmed and not any(region.role == "question" for region in payload.regions):
        raise HTTPException(422, "确认裁片前，请至少框选一处原题正文。")
    images = crop_regions(document, payload.regions) if payload.confirmed else []
    layout = layout or ExerciseLayout(draft_id=draft_id, version=0)
    layout.version += 1
    layout.regions = [region.model_dump(mode="json") for region in payload.regions]
    layout.question_type, layout.difficulty = payload.question_type, payload.difficulty
    layout.knowledge_tags = list(dict.fromkeys(payload.knowledge_tags))
    layout.status = "confirmed" if payload.confirmed else "suggested"
    layout.warnings = [] if payload.confirmed else ["裁切范围尚未确认，不能用于原题保真打印。"]
    layout.updated_at = utcnow()
    db.add(layout)
    db.execute(delete(ExerciseAsset).where(ExerciseAsset.draft_id == draft_id))
    for position, (region, data) in enumerate(zip(payload.regions, images, strict=False)):
        db.add(
            ExerciseAsset(
                draft_id=draft_id,
                layout_version=layout.version,
                role=region.role,
                position=position,
                page_number=region.page_number,
                bbox=list(region.bbox),
                data=data,
            )
        )
    db.commit()
    return layout_out(db, draft_id)
