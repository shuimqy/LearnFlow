from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

QuestionType = Literal["choice", "fill", "calculation", "proof", "short_answer", "other"]
Difficulty = Literal["basic", "intermediate", "advanced", "unknown"]
Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ChapterInput(BaseModel):
    id: str | None = Field(default=None, max_length=36)
    title: str = Field(min_length=1, max_length=200)
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("请输入章节名称")
        return value.strip()


class ChapterUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    chapters: list[ChapterInput] = Field(max_length=100)


class ChapterGuess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    start_page: int = Field(ge=1)


class ChapterDetection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chapters: list[ChapterGuess] = Field(max_length=100)
    warnings: list[str] = Field(max_length=20)


class CropRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["question", "figure"]
    page_number: int = Field(ge=1)
    bbox: tuple[Coordinate, Coordinate, Coordinate, Coordinate]

    @model_validator(mode="after")
    def valid_area(self):
        x0, y0, x1, y1 = self.bbox
        if x1 - x0 < 0.005 or y1 - y0 < 0.005:
            raise ValueError("裁切范围过小或坐标顺序有误")
        return self


class LayoutInput(BaseModel):
    expected_version: int = Field(ge=0)
    question_type: QuestionType = "other"
    difficulty: Difficulty = "unknown"
    knowledge_tags: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=12
    )
    regions: list[CropRegion] = Field(default_factory=list, max_length=12)
    confirmed: bool = False


class LayoutGuess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: str = Field(max_length=36)
    question_type: QuestionType
    difficulty: Difficulty
    knowledge_tags: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(max_length=12)
    regions: list[CropRegion] = Field(max_length=8)
    warnings: list[str] = Field(max_length=10)


class PageLayouts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exercises: list[LayoutGuess] = Field(max_length=12)
