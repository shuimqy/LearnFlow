import shutil
from collections import Counter
from typing import BinaryIO
from uuid import NAMESPACE_URL, UUID, uuid5
from zipfile import ZipFile

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Chapter,
    Course,
    Document,
    DocumentStructure,
    ExerciseAsset,
    ExerciseLayout,
    ExtractionDraft,
    KnowledgePoint,
    KnowledgeSource,
    PageExtraction,
    ProcessingTask,
)
from app.models.base import new_id, utcnow
from app.services.course_package import BLOCK_SIZE, check_document_pdf, read_course_package
from app.services.knowledge import save_revision
from app.services.storage import remove_file, storage_file


def import_course_package(
    db: Session, user_id: str, file: BinaryIO, request_id: UUID | None = None
) -> Course:
    course_id = (
        str(uuid5(NAMESPACE_URL, f"learnflow:course-import:{user_id}:{request_id}"))
        if request_id is not None
        else new_id()
    )
    owned_import = select(Course).where(Course.id == course_id, Course.user_id == user_id)
    if request_id is not None and (existing := db.scalar(owned_import)):
        return existing

    package = read_course_package(file, verify_pdfs=False)
    timestamps = utcnow()
    course = Course(id=course_id, user_id=user_id, **package.manifest.course.model_dump())
    document_ids = {record.id: new_id() for record in package.documents}
    point_ids = {record.id: new_id() for record in package.knowledge}
    page_ids = {(page.document_id, page.page_number): new_id() for page in package.pages}
    transcripts = Counter(page.document_id for page in package.pages)
    written_keys = []
    try:
        db.add(course)
        db.flush()
        with ZipFile(file) as archive:
            for record in package.documents:
                document_id = document_ids[record.id]
                key = f"documents/{document_id}.pdf"
                path = storage_file(key)
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(record.path) as source, path.open("xb") as target:
                    written_keys.append(key)
                    shutil.copyfileobj(source, target, BLOCK_SIZE)
                check_document_pdf(path, record)
                complete = transcripts[record.id] == record.page_count
                document = Document(
                    id=document_id,
                    course_id=course.id,
                    filename=record.filename,
                    storage_key=key,
                    page_count=record.page_count,
                    size_bytes=package.manifest.files[record.path].size_bytes,
                    exercise_mode=record.exercise_mode,
                    status="processed" if complete else "uploaded",
                )
                document.task = ProcessingTask(
                    status="completed" if complete else "pending",
                    stage="imported" if complete else "awaiting_extraction",
                    progress=100 * transcripts[record.id] // record.page_count,
                    finished_at=timestamps if complete else None,
                )
                db.add(document)
            db.flush()

            db.add_all(
                Chapter(
                    document_id=document_ids[record.document_id],
                    title=record.title,
                    start_page=record.start_page,
                    end_page=record.end_page,
                    position=record.position,
                    source="imported",
                )
                for record in package.chapters
            )
            db.add_all(
                DocumentStructure(
                    document_id=document_ids[document_id],
                    version=1,
                    status="completed",
                    progress=100,
                )
                for document_id in {chapter.document_id for chapter in package.chapters}
            )
            db.add_all(
                PageExtraction(
                    id=page_ids[record.document_id, record.page_number],
                    document_id=document_ids[record.document_id],
                    page_number=record.page_number,
                    status="completed",
                    transcript=record.transcript,
                    warnings=record.warnings,
                    processed_at=timestamps,
                )
                for record in package.pages
            )
            for record in package.knowledge:
                point = KnowledgePoint(
                    id=point_ids[record.id],
                    course_id=course.id,
                    title=record.title,
                    summary=record.summary,
                    content=record.content,
                    version=1,
                    status="active",
                    created_by=user_id,
                    updated_by=user_id,
                )
                # 包内引用是快照。失效课件的文件名、页码和引文也需要保留。
                point.sources = [
                    KnowledgeSource(
                        document_id=document_ids.get(source.document_id),
                        filename=source.filename,
                        page_number=source.page_number,
                        quote=source.quote,
                        position=position,
                    )
                    for position, source in enumerate(record.sources)
                ]
                db.add(point)
                save_revision(db, point, user_id, "create", "导入课程包", enqueue_index=False)

            for record in package.exercises:
                draft_id = new_id()
                db.add(
                    ExtractionDraft(
                        id=draft_id,
                        extraction_id=page_ids[record.document_id, record.page_number],
                        position=record.position,
                        kind=record.example.kind,
                        title=record.title,
                        summary=record.summary,
                        content=record.example.question,
                        formulas=[formula.model_dump() for formula in record.example.formulas],
                        warnings=record.warnings,
                        example=record.example.model_dump(),
                        status="imported",
                        knowledge_id=point_ids[record.knowledge_id],
                    )
                )
                if layout := record.layout:
                    db.flush()
                    db.add(
                        ExerciseLayout(
                            draft_id=draft_id,
                            version=1,
                            status=layout.status,
                            question_type=layout.question_type,
                            difficulty=layout.difficulty,
                            knowledge_tags=layout.knowledge_tags,
                            warnings=layout.warnings,
                            regions=[region.model_dump(mode="json") for region in layout.regions],
                        )
                    )
                    db.add_all(
                        ExerciseAsset(
                            draft_id=draft_id,
                            layout_version=1,
                            role=asset.role,
                            position=asset.position,
                            page_number=asset.page_number,
                            bbox=list(asset.bbox),
                            data=archive.read(asset.path),
                        )
                        for asset in layout.assets
                    )
                    db.flush()
        db.commit()
        return course
    except Exception as exc:
        db.rollback()
        for key in written_keys:
            remove_file(key)
        if (
            request_id is not None
            and isinstance(exc, IntegrityError)
            and (existing := db.scalar(owned_import))
        ):
            return existing
        raise
