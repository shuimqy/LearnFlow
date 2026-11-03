from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.base import Output


class SourceInput(BaseModel):
    document_id: str | None = Field(default=None, min_length=1, max_length=36)
    source_id: str | None = Field(default=None, min_length=1, max_length=36)
    page_number: int = Field(ge=1)
    quote: str = Field(default="", max_length=50000)

    @model_validator(mode="after")
    def reference_required(self):
        if not self.document_id and not self.source_id:
            raise ValueError("缺少来源")
        return self


class KnowledgeInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    content: str = Field(min_length=1, max_length=100000)
    sources: list[SourceInput] = Field(default_factory=list, max_length=20)

    @field_validator("title", "content")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()


class KnowledgeUpdate(KnowledgeInput):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_not_blank(cls, value):
        if not value.strip():
            raise ValueError("请填写修改原因")
        return value.strip()


class SourceOut(Output):
    id: str
    document_id: str | None
    fragment_id: str | None
    filename: str
    page_number: int
    quote: str


class KnowledgeOut(Output):
    id: str
    course_id: str
    title: str
    summary: str
    content: str
    version: int
    status: str
    created_at: datetime
    updated_at: datetime
    sources: list[SourceOut]


class PageOut(Output):
    id: str
    document_id: str
    page_number: int
    text: str
    status: str
    parser_version: str


class RevisionOut(Output):
    id: str
    knowledge_id: str
    version: int
    snapshot: dict
    operation: str
    reason: str
    created_at: datetime


class RestoreInput(BaseModel):
    revision_id: str = Field(min_length=1, max_length=36)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class ProposalInput(KnowledgeUpdate):
    pass


class ProposalOut(Output):
    id: str
    knowledge_id: str
    base_version: int
    proposed: dict
    reason: str
    status: str
    created_at: datetime
    resolved_at: datetime | None
    processing: bool
    llm_review: dict | None


class ProposalResolutionOut(KnowledgeOut):
    processing: dict


class ConfirmInput(BaseModel):
    expected_version: int = Field(ge=1)


class ExclusionInput(BaseModel):
    excluded: bool
    reason: str = Field(min_length=1, max_length=2000)


class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def trim_query(cls, value):
        if not value.strip():
            raise ValueError("请输入检索词")
        return value.strip()


class SearchHit(Output):
    knowledge_id: str
    title: str
    version: int
    text: str
    sources: list[SourceOut]
    match_type: Literal["text"] = "text"
