from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.base import Output


class ExerciseInput(BaseModel):
    draft_id: str = Field(min_length=1, max_length=36)
    source_version: int = Field(ge=1)
    layout_version: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=20000)
    answer: str = Field(default="", max_length=10000)
    solution: str = Field(default="", max_length=20000)

    @field_validator("title", "question")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("题目内容不能为空")
        return value.strip()


class SectionInput(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    items: list[ExerciseInput] = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("分组名称不能为空")
        return value.strip()


class WorkbookSettings(BaseModel):
    print_mode: Literal["text", "original"] = "text"
    include_answers: bool = True
    answer_space: Literal["compact", "medium", "large", "page"] = "medium"
    show_sources: bool = True


class WorkbookInput(BaseModel):
    expected_version: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=160)
    sections: list[SectionInput] = Field(min_length=1, max_length=30)
    settings: WorkbookSettings = Field(default_factory=WorkbookSettings)

    @field_validator("title")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("请输入做题本名称")
        return value.strip()

    @model_validator(mode="after")
    def bounded_items(self):
        items = [item for group in self.sections for item in group.items]
        if len(items) > 100 or len({item.draft_id for item in items}) != len(items):
            raise ValueError("最多选择 100 道不同的题目")
        if (
            sum(len(item.question) + len(item.answer) + len(item.solution) for item in items)
            > 300000
        ):
            raise ValueError("内容过长，请拆成多本")
        return self


class WorkbookSummary(Output):
    id: str
    course_id: str
    title: str
    version: int
    created_at: datetime
    updated_at: datetime


class WorkbookRename(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("请输入做题本名称")
        return value.strip()


class WorkbookOut(WorkbookSummary):
    sections: list[dict]
    settings: WorkbookSettings
