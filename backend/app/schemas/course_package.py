from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.course import CourseInput
from app.schemas.document import ExerciseMode
from app.schemas.document_structure import CropRegion, Difficulty, QuestionType
from app.schemas.extraction import ExtractedExample

PackageID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
SHA256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
PageNumber = Annotated[int, Field(ge=1)]
Position = Annotated[int, Field(ge=0)]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Member(Record):
    size_bytes: int = Field(ge=0)
    sha256: SHA256


class CourseRecord(CourseInput):
    model_config = ConfigDict(extra="forbid", strict=True)


class Manifest(Record):
    format: Literal["learnflow.course"]
    format_version: Literal[1]
    course: CourseRecord
    files: dict[str, Member]


class DocumentRecord(Record):
    id: PackageID
    filename: str = Field(min_length=1, max_length=255)
    path: str
    page_count: PageNumber
    exercise_mode: ExerciseMode


class ChapterRecord(Record):
    document_id: PackageID
    title: str = Field(min_length=1, max_length=200)
    start_page: PageNumber
    end_page: PageNumber
    position: Position


class PageRecord(Record):
    document_id: PackageID
    page_number: PageNumber
    transcript: str
    warnings: list[str]


class SourceRecord(Record):
    document_id: PackageID | None
    filename: str = Field(max_length=255)
    page_number: PageNumber
    quote: str


class KnowledgeRecord(Record):
    id: PackageID
    title: str = Field(min_length=1, max_length=200)
    summary: str
    content: str = Field(min_length=1)
    sources: list[SourceRecord]


class AssetRecord(CropRegion):
    id: PackageID
    path: str
    position: Position


class LayoutRecord(Record):
    status: Literal["pending", "unavailable", "suggested", "confirmed"]
    question_type: QuestionType
    difficulty: Difficulty
    knowledge_tags: list[str]
    warnings: list[str]
    regions: list[CropRegion]
    assets: list[AssetRecord]


class ExerciseRecord(Record):
    id: PackageID
    document_id: PackageID
    page_number: PageNumber
    position: Position
    knowledge_id: PackageID
    title: str = Field(min_length=1, max_length=200)
    summary: str
    warnings: list[str]
    example: ExtractedExample
    layout: LayoutRecord | None


class ChunkRecord(Record):
    knowledge_id: PackageID
    position: Position
    content_sha256: SHA256


class EmbeddingModel(Record):
    provider: str
    model: str
    revision: str
    dimensions: int = Field(ge=1)
    fingerprint: SHA256


class Chunking(Record):
    algorithm: Literal["characters-prefer-newline"] = "characters-prefer-newline"
    size: int = Field(ge=1)
    overlap: int = Field(ge=0)
    text_format: str


class EmbeddingIndex(Record):
    model: EmbeddingModel
    vectors_path: str
    vector_format: Literal["jsonl-float32"]


class EmbeddingMetadata(Record):
    chunking: Chunking
    configured_model: EmbeddingModel | None
    chunks_path: Literal["chunks.jsonl"] = "chunks.jsonl"
    indexes: list[EmbeddingIndex] = Field(max_length=0)
