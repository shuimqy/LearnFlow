from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.base import Output

ShortText = Annotated[str, Field(min_length=1, max_length=500)]


class Formula(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    latex: str = Field(min_length=1, max_length=4000)
    explanation: str = Field(max_length=1000)
    uncertain: bool

    @field_validator("latex")
    @classmethod
    def plain_latex(cls, value):
        value = value.strip()
        if not value or "$" in value or "\\[" in value or "\\]" in value:
            raise ValueError("请只填写 LaTeX 公式本身，不含公式分隔符")
        return value


class ExtractedKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(max_length=2000)
    content: str = Field(min_length=1, max_length=20000)
    formulas: list[Formula] = Field(max_length=20)
    warnings: list[ShortText] = Field(max_length=20)

    @field_validator("title", "content")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()


class ExtractedExample(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["worked_example", "exercise"]
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=20000)
    answer: str = Field(max_length=10000)
    solution: str = Field(max_length=20000)
    formulas: list[Formula] = Field(max_length=20)
    warnings: list[ShortText] = Field(max_length=20)


class ExtractedPage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    transcript: str = Field(max_length=40000)
    warnings: list[ShortText] = Field(max_length=20)
    knowledge: list[ExtractedKnowledge] = Field(max_length=12)
    examples: list[ExtractedExample] = Field(max_length=12)


class AcceptDraft(ExtractedKnowledge):
    formula_reviewed: bool = False
    example: ExtractedExample | None = None


class DraftOut(Output):
    id: str
    title: str
    summary: str
    content: str
    formulas: list[Formula]
    warnings: list[str]
    status: str
    knowledge_id: str | None
    kind: str
    example: ExtractedExample | None


class ExtractionPageOut(Output):
    id: str
    page_number: int
    status: str
    transcript: str
    warnings: list[str]
    error: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    processed_at: datetime | None
    drafts: list[DraftOut]
