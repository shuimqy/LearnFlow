import hashlib
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pymupdf
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Chapter,
    Course,
    Document,
    ExerciseAsset,
    ExerciseLayout,
    ExtractionDraft,
    KnowledgeChunk,
    KnowledgePoint,
    PageExtraction,
)
from app.schemas.course_package import (
    AssetRecord,
    ChapterRecord,
    Chunking,
    ChunkRecord,
    CourseRecord,
    DocumentRecord,
    EmbeddingMetadata,
    EmbeddingModel,
    ExerciseRecord,
    KnowledgeRecord,
    LayoutRecord,
    Manifest,
    Member,
    PageRecord,
    SourceRecord,
)
from app.services.account_models import default_config, fingerprint, profile_for
from app.services.knowledge_index import CHUNK_OVERLAP, CHUNK_SIZE, CHUNK_TEXT_FORMAT, chunk_texts
from app.services.storage import storage_file
from app.services.workbooks import exercise_statement

DATA_MEMBERS = {
    "documents.json",
    "chapters.json",
    "pages.jsonl",
    "knowledge.jsonl",
    "exercises.jsonl",
    "embedding.json",
    "chunks.jsonl",
}
BLOCK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class CoursePackageContents:
    manifest: Manifest
    documents: list[DocumentRecord]
    chapters: list[ChapterRecord]
    pages: list[PageRecord]
    knowledge: list[KnowledgeRecord]
    exercises: list[ExerciseRecord]
    embedding: EmbeddingMetadata
    chunk_count: int


def package_chunking():
    return Chunking(size=CHUNK_SIZE, overlap=CHUNK_OVERLAP, text_format=CHUNK_TEXT_FORMAT)


def embedding_metadata(db, user_id):
    profile = profile_for(db, user_id, "embedding")
    config = profile.config if profile else default_config("embedding")
    model = None
    if config["model"] and config["base_url"]:
        model = EmbeddingModel(
            provider=config["provider"],
            model=config["model"],
            revision=config["revision"],
            dimensions=config["dimensions"],
            fingerprint=fingerprint(config),
        )
    return EmbeddingMetadata(chunking=package_chunking(), configured_model=model, indexes=[])


def exercise_records(db, course_id):
    rows = db.execute(
        exercise_statement(course_id).order_by(
            Document.id, PageExtraction.page_number, ExtractionDraft.position
        )
    ).all()
    layouts = {
        item.draft_id: item
        for item in db.scalars(
            select(ExerciseLayout)
            .join(ExtractionDraft, ExtractionDraft.id == ExerciseLayout.draft_id)
            .join(PageExtraction)
            .join(Document)
            .where(Document.course_id == course_id)
        )
    }
    valid_draft_ids = {draft.id for draft, _, _, _ in rows}
    assets_by_draft = defaultdict(list)
    for asset in db.scalars(
        select(ExerciseAsset)
        .join(ExerciseLayout, ExerciseLayout.draft_id == ExerciseAsset.draft_id)
        .join(ExtractionDraft, ExtractionDraft.id == ExerciseAsset.draft_id)
        .join(PageExtraction)
        .join(Document)
        .where(
            Document.course_id == course_id, ExerciseAsset.layout_version == ExerciseLayout.version
        )
        .order_by(ExerciseAsset.position, ExerciseAsset.id)
    ):
        if asset.draft_id in valid_draft_ids:
            assets_by_draft[asset.draft_id].append(asset)

    records = []
    for draft, page, document, point in rows:
        layout = layouts.get(draft.id)
        records.append(
            ExerciseRecord(
                id=draft.id,
                document_id=document.id,
                page_number=page.page_number,
                position=draft.position,
                knowledge_id=point.id,
                title=draft.title,
                summary=draft.summary,
                warnings=draft.warnings,
                example={
                    "title": draft.title,
                    "answer": "",
                    "solution": "",
                    "formulas": draft.formulas,
                    "warnings": [],
                    **draft.example,
                    "kind": draft.kind,
                },
                layout=LayoutRecord(
                    status=layout.status,
                    question_type=layout.question_type,
                    difficulty=layout.difficulty,
                    knowledge_tags=layout.knowledge_tags,
                    warnings=layout.warnings,
                    regions=layout.regions,
                    assets=[
                        AssetRecord(
                            id=asset.id,
                            path=f"files/assets/{asset.id}.png",
                            position=asset.position,
                            role=asset.role,
                            page_number=asset.page_number,
                            bbox=tuple(asset.bbox),
                        )
                        for asset in assets_by_draft[draft.id]
                    ],
                )
                if layout
                else None,
            )
        )
    return records, assets_by_draft


def lines(records):
    for record in records:
        yield record.model_dump_json().encode("utf-8") + b"\n"


def write_member(archive, members, name, blocks):
    info = ZipInfo(name)
    info.compress_type = ZIP_DEFLATED if name.endswith((".json", ".jsonl")) else ZIP_STORED
    digest = hashlib.sha256()
    size = 0
    with archive.open(info, "w", force_zip64=name.endswith(".pdf")) as member:
        for block in blocks:
            member.write(block)
            digest.update(block)
            size += len(block)
    members[name] = Member(size_bytes=size, sha256=digest.hexdigest())


def export_course_package(db: Session, course_id: str, user_id: str, path: Path):
    course = db.scalar(select(Course).where(Course.id == course_id, Course.user_id == user_id))
    if not course:
        raise ValueError("Course not found for this owner")
    documents = db.scalars(
        select(Document).where(Document.course_id == course.id).order_by(Document.id)
    ).all()
    document_rows = [
        DocumentRecord(
            id=d.id,
            filename=d.filename,
            path=f"files/documents/{d.id}.pdf",
            page_count=d.page_count,
            exercise_mode=d.exercise_mode,
        )
        for d in documents
    ]
    chapters = db.scalars(
        select(Chapter)
        .join(Document)
        .where(Document.course_id == course.id)
        .order_by(Chapter.document_id, Chapter.position)
    ).all()
    chapter_rows = [
        ChapterRecord(
            document_id=c.document_id,
            title=c.title,
            start_page=c.start_page,
            end_page=c.end_page,
            position=c.position,
        )
        for c in chapters
    ]
    pages = db.scalars(
        select(PageExtraction)
        .join(Document)
        .where(Document.course_id == course.id, PageExtraction.status == "completed")
        .order_by(PageExtraction.document_id, PageExtraction.page_number)
    )
    points = db.scalars(
        select(KnowledgePoint)
        .options(selectinload(KnowledgePoint.sources))
        .where(KnowledgePoint.course_id == course.id, KnowledgePoint.status == "active")
        .order_by(KnowledgePoint.id)
    )
    chunks = db.execute(
        select(KnowledgeChunk.knowledge_id, KnowledgeChunk.position, KnowledgeChunk.content_hash)
        .join(KnowledgePoint, KnowledgePoint.id == KnowledgeChunk.knowledge_id)
        .where(
            KnowledgeChunk.course_id == course.id,
            KnowledgePoint.course_id == course.id,
            KnowledgePoint.status == "active",
            KnowledgeChunk.version == KnowledgePoint.version,
        )
        .order_by(KnowledgeChunk.knowledge_id, KnowledgeChunk.position)
    )
    exercises, assets_by_draft = exercise_records(db, course.id)
    members = {}
    with ZipFile(path, "x") as archive:
        write_member(
            archive,
            members,
            "documents.json",
            [TypeAdapter(list[DocumentRecord]).dump_json(document_rows)],
        )
        write_member(
            archive,
            members,
            "chapters.json",
            [TypeAdapter(list[ChapterRecord]).dump_json(chapter_rows)],
        )
        write_member(
            archive,
            members,
            "pages.jsonl",
            lines(
                PageRecord(
                    document_id=p.document_id,
                    page_number=p.page_number,
                    transcript=p.transcript,
                    warnings=p.warnings,
                )
                for p in pages
            ),
        )
        write_member(
            archive,
            members,
            "knowledge.jsonl",
            lines(
                KnowledgeRecord(
                    id=p.id,
                    title=p.title,
                    summary=p.summary,
                    content=p.content,
                    sources=[
                        SourceRecord(
                            document_id=s.document_id,
                            filename=s.filename,
                            page_number=s.page_number,
                            quote=s.quote,
                        )
                        for s in p.sources
                    ],
                )
                for p in points
            ),
        )
        write_member(archive, members, "exercises.jsonl", lines(exercises))
        write_member(
            archive,
            members,
            "embedding.json",
            [embedding_metadata(db, user_id).model_dump_json().encode()],
        )
        write_member(
            archive,
            members,
            "chunks.jsonl",
            lines(
                ChunkRecord(knowledge_id=point, position=position, content_sha256=digest)
                for point, position, digest in chunks
            ),
        )
        for document, record in zip(documents, document_rows, strict=True):
            with storage_file(document.storage_key).open("rb") as file:
                write_member(
                    archive, members, record.path, iter(lambda: file.read(BLOCK_SIZE), b"")
                )
            if members[record.path].size_bytes != document.size_bytes:
                raise ValueError(f"Course file size changed during export: {document.filename}")
        for assets in assets_by_draft.values():
            for asset in assets:
                write_member(archive, members, f"files/assets/{asset.id}.png", [asset.data])
                db.expire(asset, ["data"])
        manifest = Manifest(
            format="learnflow.course",
            format_version=1,
            course=CourseRecord(
                name=course.name, description=course.description, color=course.color
            ),
            files=members,
        )
        archive.writestr("manifest.json", manifest.model_dump_json(indent=2))


def read_lines(archive, name, schema):
    with archive.open(name) as member:
        return [schema.model_validate_json(line) for line in member if line.strip()]


def check_manifest(archive):
    manifest = Manifest.model_validate_json(archive.read("manifest.json"))
    names = archive.namelist()
    if len(names) != len(set(names)) or set(names) != {"manifest.json", *manifest.files}:
        raise ValueError("Package contents do not match the manifest")
    if not DATA_MEMBERS.issubset(manifest.files):
        raise ValueError("Required records are missing from the course package")
    for name, expected in manifest.files.items():
        if archive.getinfo(name).file_size != expected.size_bytes:
            raise ValueError(f"File size mismatch for {name}")
        with archive.open(name) as member:
            if hashlib.file_digest(member, "sha256").hexdigest() != expected.sha256:
                raise ValueError(f"SHA-256 mismatch for {name}")
    return manifest


def check_pdf_pages(archive, documents):
    if not documents:
        return
    with TemporaryDirectory(prefix="learnflow-course-check-") as folder:
        path = Path(folder) / "document.pdf"
        for document in documents:
            with archive.open(document.path) as source, path.open("wb") as target:
                shutil.copyfileobj(source, target, BLOCK_SIZE)
            check_document_pdf(path, document)


def check_document_pdf(path: Path, document: DocumentRecord):
    try:
        with pymupdf.open(path) as pdf:
            valid = pdf.is_pdf and not pdf.needs_pass and pdf.page_count == document.page_count
    except (pymupdf.FileDataError, OSError):
        valid = False
    if not valid:
        raise ValueError(f"Invalid PDF or page count for {document.filename}")


def read_course_package(file, *, verify_pdfs: bool = True) -> CoursePackageContents:
    with ZipFile(file) as archive:
        manifest = check_manifest(archive)
        documents = TypeAdapter(list[DocumentRecord]).validate_json(archive.read("documents.json"))
        chapters = TypeAdapter(list[ChapterRecord]).validate_json(archive.read("chapters.json"))
        pages = read_lines(archive, "pages.jsonl", PageRecord)
        knowledge = read_lines(archive, "knowledge.jsonl", KnowledgeRecord)
        exercises = read_lines(archive, "exercises.jsonl", ExerciseRecord)
        chunks = read_lines(archive, "chunks.jsonl", ChunkRecord)
        embedding = EmbeddingMetadata.model_validate_json(archive.read("embedding.json"))

        page_count = {document.id: document.page_count for document in documents}
        page_keys = {(page.document_id, page.page_number) for page in pages}
        knowledge_ids = {point.id for point in knowledge}
        if (
            len(page_count) != len(documents)
            or len(page_keys) != len(pages)
            or len(knowledge_ids) != len(knowledge)
        ):
            raise ValueError("Duplicate document, page or knowledge ID")

        def valid_page(document_id, page):
            return page <= page_count.get(document_id, 0)

        expected_files = set(DATA_MEMBERS)
        for document in documents:
            if document.path != f"files/documents/{document.id}.pdf":
                raise ValueError("Invalid PDF path in document record")
            expected_files.add(document.path)
        if any(not valid_page(p.document_id, p.page_number) for p in pages):
            raise ValueError("An extracted page is outside its PDF")
        chapter_ends = {}
        for chapter in sorted(chapters, key=lambda c: (c.document_id, c.position)):
            previous = chapter_ends.get(chapter.document_id, (0, -1))
            if (
                not previous[0] < chapter.start_page <= chapter.end_page
                or previous[1] >= chapter.position
                or not valid_page(chapter.document_id, chapter.end_page)
            ):
                raise ValueError("Invalid chapter order or PDF page range")
            chapter_ends[chapter.document_id] = (chapter.end_page, chapter.position)
        for point in knowledge:
            if any(
                s.document_id is not None and not valid_page(s.document_id, s.page_number)
                for s in point.sources
            ):
                raise ValueError("A knowledge reference points outside its PDF")

        seen_ids, positions, assets = set(), set(), set()
        for exercise in exercises:
            key = (exercise.document_id, exercise.page_number, exercise.position)
            if (
                exercise.id in seen_ids
                or key in positions
                or exercise.knowledge_id not in knowledge_ids
                or key[:2] not in page_keys
            ):
                raise ValueError("Invalid exercise ID, page or linked knowledge")
            seen_ids.add(exercise.id)
            positions.add(key)
            if layout := exercise.layout:
                if any(
                    not valid_page(exercise.document_id, region.page_number)
                    for region in layout.regions
                ):
                    raise ValueError("An exercise crop is outside its PDF")
                regions = {
                    (region.role, region.page_number, region.bbox) for region in layout.regions
                }
                if layout.status == "confirmed" and not any(
                    a.role == "question" for a in layout.assets
                ):
                    raise ValueError("Confirmed original exercise crop is missing")
                for asset in layout.assets:
                    if (
                        asset.id in assets
                        or asset.path != f"files/assets/{asset.id}.png"
                        or (asset.role, asset.page_number, asset.bbox) not in regions
                    ):
                        raise ValueError("Invalid asset ID, path or crop reference")
                    assets.add(asset.id)
                    expected_files.add(asset.path)
                    with archive.open(asset.path) as image:
                        if image.read(8) != b"\x89PNG\r\n\x1a\n":
                            raise ValueError("An exercise asset is not PNG data")

        if manifest.files.keys() != expected_files:
            raise ValueError("The manifest contains missing or unreferenced course files")
        if embedding.chunking != package_chunking():
            raise ValueError("Unsupported chunking metadata")
        expected_chunks = {
            (point.id, position): hashlib.sha256(text.encode()).hexdigest()
            for point in knowledge
            for position, text in enumerate(chunk_texts(point.title, point.summary, point.content))
        }
        chunk_hashes = {
            (chunk.knowledge_id, chunk.position): chunk.content_sha256 for chunk in chunks
        }
        if len(chunk_hashes) != len(chunks) or chunk_hashes != expected_chunks:
            raise ValueError("Chunk hashes do not match the exported knowledge")
        if verify_pdfs:
            check_pdf_pages(archive, documents)

    return CoursePackageContents(
        manifest, documents, chapters, pages, knowledge, exercises, embedding, len(chunks)
    )


def validate_course_package(path: Path) -> dict:
    package = read_course_package(path)
    return {
        "format_version": package.manifest.format_version,
        "course": package.manifest.course.name,
        "documents": len(package.documents),
        "pdf_pages": sum(document.page_count for document in package.documents),
        "chapters": len(package.chapters),
        "page_transcripts": len(package.pages),
        "knowledge": len(package.knowledge),
        "exercises": len(package.exercises),
        "practice": sum(e.example.kind == "exercise" for e in package.exercises),
        "worked_examples": sum(e.example.kind == "worked_example" for e in package.exercises),
        "assets": sum(len(e.layout.assets) for e in package.exercises if e.layout),
        "chunks": package.chunk_count,
        "embedding": package.embedding.model_dump(),
    }
