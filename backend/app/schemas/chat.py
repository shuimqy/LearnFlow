from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.base import Output


class ConversationInput(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=120)


class ChatImageOut(Output):
    id: str
    filename: str
    media_type: str
    size: int
    width: int
    height: int


class ConversationOut(Output):
    id: str
    course_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    parent_conversation_id: str | None
    parent_message_id: str | None
    anchor_text: str
    context_mode: str | None
    source_question: str
    context_truncated: bool
    source_images: list[ChatImageOut]


class BranchInput(BaseModel):
    request_id: UUID
    parent_message_id: UUID
    question: str = Field(min_length=1, max_length=2000)
    anchor_text: str = Field(default="", max_length=6000)
    context_mode: Literal["focused", "full", "minimal"] = "focused"

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value):
        if not value.strip():
            raise ValueError("请输入分支问题")
        return value.strip()


class QuestionInput(BaseModel):
    content: str = Field(default="", max_length=2000)
    request_id: UUID

    @field_validator("content")
    @classmethod
    def not_blank(cls, value):
        return value.strip()


class MessageOut(Output):
    id: str
    conversation_id: str
    sequence: int
    request_id: str
    role: str
    images: list[ChatImageOut]
    content: str
    supplement: str
    status: str
    workflow_stage: str | None
    citations: list[dict]
    warnings: list[str]
    retrieval_mode: str | None
    model: str | None
    input_tokens: int
    output_tokens: int
    error: str | None
    created_at: datetime


class AnswerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["answered", "insufficient", "conversation", "needs_retrieval"]
    answer: str = Field(min_length=1, max_length=24000)
    supplement: str = Field(max_length=10000)
    citations: list[str] = Field(max_length=6)

    @model_validator(mode="after")
    def grounded_answer(self):
        if not self.answer.strip() or (self.status == "answered" and not self.citations):
            raise ValueError("An answer needs text and evidence")
        if self.status == "insufficient" and self.supplement.strip():
            raise ValueError("Do not supplement an unsupported answer")
        if self.status == "conversation" and (self.citations or self.supplement.strip()):
            raise ValueError("Conversation recall must not contain course evidence or supplements")
        if self.status == "needs_retrieval" and (self.citations or self.supplement.strip()):
            raise ValueError("Retrieval requests must not contain an answer or citations")
        return self


class ChatPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    route: Literal["chat", "history", "context", "retrieve", "clarify", "image"]
    query: str = Field(max_length=2000)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value):
        return value.strip()


class ConversationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(min_length=1, max_length=12000)
    needs_retrieval: bool
    query: str = Field(max_length=2000)

    @field_validator("answer")
    @classmethod
    def nonblank_answer(cls, value):
        if not value.strip():
            raise ValueError("An answer needs text")
        return value


class ImageObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    description: str = Field(min_length=1, max_length=12000)
    warnings: list[str] = Field(max_length=4)

    @field_validator("description")
    @classmethod
    def nonblank_description(cls, value):
        if not value.strip():
            raise ValueError("An image observation needs visible content")
        return value.strip()

    @field_validator("warnings")
    @classmethod
    def bounded_warnings(cls, values):
        if any(not value.strip() or len(value) > 300 for value in values):
            raise ValueError("Image warnings must be short")
        return values
