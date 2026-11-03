from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.document_structure import Difficulty, QuestionType


class TypeQuota(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_type: QuestionType
    count: int = Field(ge=1, le=100)


class DifficultyQuota(BaseModel):
    model_config = ConfigDict(extra="forbid")
    difficulty: Difficulty
    count: int = Field(ge=1, le=100)


class AssemblyInput(BaseModel):
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)
    selection_mode: Literal["auto", "count", "all"] = "auto"
    instructions: str = Field(default="", max_length=2000)
    chapter_ids: list[str] = Field(default_factory=list, max_length=100)
    count: int | None = Field(default=None, ge=1, le=100)
    type_counts: list[TypeQuota] = Field(default_factory=list, max_length=6)
    difficulty_counts: list[DifficultyQuota] = Field(default_factory=list, max_length=4)
    require_crops: bool = False
    exclude_ids: list[str] = Field(default_factory=list, max_length=100)


class AssemblyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="", max_length=160)
    count: int | None = Field(default=10, ge=1, le=100)
    selection_mode: Literal["count", "all"] = "count"
    chapter_ids: list[str] = Field(max_length=100)
    type_counts: list[TypeQuota] = Field(max_length=6)
    difficulty_counts: list[DifficultyQuota] = Field(max_length=4)
    topics: list[str] = Field(max_length=12)
    warnings: list[str] = Field(max_length=10)
    scope_resolved: bool = True


class SelectionOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_ids: list[str] = Field(max_length=300)
    explanation: str = Field(max_length=1000)
