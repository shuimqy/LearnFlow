from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import Output

CourseColor = Literal["sage", "sand", "blue", "rose", "lavender"]


class CourseInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    color: CourseColor = "sage"

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if not value.strip():
            raise ValueError("请输入课程名称")
        return value.strip()


class CourseOut(Output):
    id: str
    name: str
    description: str
    color: str
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
