import hashlib

import pymupdf
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentPage, KnowledgePoint, KnowledgeSource, SourceFragment
from app.schemas.knowledge import SourceInput
from app.services.storage import storage_file


def extract_page(db: Session, document: Document, page_number: int) -> DocumentPage:
    if not 1 <= page_number <= document.page_count:
        raise HTTPException(422, "引用页码超出了课件范围")
    cached = db.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document.id, DocumentPage.page_number == page_number
        )
    )
    if cached:
        return cached
    path = storage_file(document.storage_key)
    if not path.is_file():
        raise HTTPException(404, "原始文件已丢失，无法读取来源")
    try:
        with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as pdf:
            page = pdf[page_number - 1]
            text = page.get_text(sort=True)
            status = "extracted" if text.strip() else "needs_ocr" if page.get_images() else "empty"
    except (pymupdf.FileDataError, RuntimeError, IndexError) as exc:
        raise HTTPException(422, "该页暂时无法读取，请检查原始课件") from exc
    result = DocumentPage(
        course_id=document.course_id,
        document_id=document.id,
        page_number=page_number,
        text=text,
        status=status,
        parser_version=f"pymupdf-{pymupdf.VersionBind}:text-sort-v1",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    db.add(result)
    db.flush()
    return result


def resolve_sources(
    db: Session,
    course_id: str,
    inputs: list[SourceInput],
    point: KnowledgePoint | None = None,
) -> list[KnowledgeSource]:
    sources = []
    seen = set()
    for item in inputs:
        if item.document_id is None:
            old = (
                next((source for source in point.sources if source.id == item.source_id), None)
                if point
                else None
            )
            if not old:
                raise HTTPException(422, "原引用不存在，请刷新后重试")
            sources.append(
                KnowledgeSource(
                    document_id=old.document_id,
                    fragment_id=old.fragment_id,
                    filename=old.filename,
                    page_number=old.page_number,
                    quote=old.quote,
                    position=len(sources),
                )
            )
            continue
        document = db.scalar(
            select(Document).where(Document.id == item.document_id, Document.course_id == course_id)
        )
        if not document:
            raise HTTPException(422, "引用的课件不属于当前课程，或已被删除")
        page = extract_page(db, document, item.page_number)
        quote = item.quote.strip() or page.text
        start = page.text.find(quote)
        if start < 0:
            raise HTTPException(422, "引用文字与该页原文不匹配，请重新读取原文后选择")
        end = start + len(quote)
        reference = (page.id, start, end)
        if reference in seen:
            continue
        seen.add(reference)
        fragment = db.scalar(
            select(SourceFragment).where(
                SourceFragment.page_id == page.id,
                SourceFragment.char_start == start,
                SourceFragment.char_end == end,
            )
        )
        if not fragment:
            fragment = SourceFragment(
                course_id=course_id,
                page_id=page.id,
                char_start=start,
                char_end=end,
                text=quote,
            )
            db.add(fragment)
            db.flush()
        sources.append(
            KnowledgeSource(
                document_id=document.id,
                fragment_id=fragment.id,
                filename=document.filename,
                page_number=page.page_number,
                quote=quote,
                position=len(sources),
            )
        )
    return sources


def source_snapshot(sources: list[KnowledgeSource]) -> list[dict]:
    return [
        {
            "document_id": source.document_id,
            "fragment_id": source.fragment_id,
            "filename": source.filename,
            "page_number": source.page_number,
            "quote": source.quote,
        }
        for source in sources
    ]


def restore_sources(db: Session, course_id: str, snapshots: list[dict]) -> list[KnowledgeSource]:
    result = []
    for position, saved in enumerate(snapshots):
        document = db.scalar(
            select(Document).where(
                Document.id == saved.get("document_id"), Document.course_id == course_id
            )
        )
        fragment = (
            db.scalar(
                select(SourceFragment).where(
                    SourceFragment.id == saved.get("fragment_id"),
                    SourceFragment.course_id == course_id,
                )
            )
            if document
            else None
        )
        result.append(
            KnowledgeSource(
                document_id=document.id if document else None,
                fragment_id=fragment.id if fragment else None,
                filename=saved["filename"],
                page_number=saved["page_number"],
                quote=saved["quote"],
                position=position,
            )
        )
    return result
