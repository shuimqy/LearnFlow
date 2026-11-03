from fastapi import HTTPException
from sqlalchemy import or_, select

from app.models import Document, PageExtraction


def validate_sources(db, course_id, document_ids):
    if document_ids is None:
        return
    if not document_ids:
        raise HTTPException(422, "请至少选择一份来源课件。")
    owned = set(
        db.scalars(
            select(Document.id).where(
                Document.course_id == course_id, Document.id.in_(document_ids)
            )
        )
    )
    if set(document_ids) != owned:
        raise HTTPException(404, "来源课件不存在或不属于当前课程。")


def filter_scope(statement, chapters, document_ids, chapter_ids, page_from, page_to):
    if page_from and page_to and page_from > page_to:
        raise HTTPException(422, "起始页不能大于结束页。")
    if document_ids is not None:
        statement = statement.where(Document.id.in_(document_ids))
    allowed = {chapter["id"]: chapter for chapter in chapters}
    if any(key not in allowed for key in chapter_ids):
        raise HTTPException(422, "指定章节不属于所选课件，请重新选择范围。")
    if chapter_ids:
        statement = statement.where(
            or_(
                *[
                    (Document.id == allowed[key]["document_id"])
                    & PageExtraction.page_number.between(
                        allowed[key]["start_page"], allowed[key]["end_page"]
                    )
                    for key in chapter_ids
                ]
            )
        )
    if page_from:
        statement = statement.where(PageExtraction.page_number >= page_from)
    if page_to:
        statement = statement.where(PageExtraction.page_number <= page_to)
    return statement
