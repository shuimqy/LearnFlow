from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, Document
from app.services.pdf_pages import render_page


@dataclass(frozen=True)
class ReferencedPageImage:
    reference: str
    filename: str
    page_number: int
    data: bytes


def reference_pages(items):
    return {
        f"{item['key']}.{position}": source
        for item in items
        for position, source in enumerate(item["sources"], 1)
        if source.get("document_id")
    }


def read_reference_pages(
    db: Session, course_id: str, user_id: str, items: list[dict], requests: list[str]
) -> list[ReferencedPageImage]:
    references = reference_pages(items)
    pages = []
    for reference in requests:
        source = references.get(reference)
        if not source:
            continue
        document = db.scalar(
            select(Document)
            .join(Course)
            .where(
                Document.id == source["document_id"],
                Document.course_id == course_id,
                Course.user_id == user_id,
            )
        )
        if not document:
            continue
        page_number = source["page_number"]
        try:
            # 1600 像素的 RGB 页图可留在模型接口的单图 8 MiB 限制内。
            image = render_page(document, page_number, max_side=1600)
        except (HTTPException, OSError):
            continue
        pages.append(ReferencedPageImage(reference, document.filename, page_number, image))
    return pages
