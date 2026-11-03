from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.base import Output


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value):
        return value.lower()


class Register(Credentials):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if not value.strip():
            raise ValueError("请输入称呼")
        return value.strip()


class UserOut(Output):
    id: str
    email: str
    name: str


class SessionOut(UserOut):
    mode: Literal["personal", "multiuser"] = "multiuser"
