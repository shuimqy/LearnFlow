from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from app.services.model_api import ModelAPIError, validate_model_endpoint


class AccountUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value):
        if not value.strip():
            raise ValueError("请输入称呼")
        return value.strip()


class ModelInput(BaseModel):
    expected_version: int = Field(ge=0)
    provider: Literal["aliyun", "deepseek", "siliconflow", "openai_compatible"]
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_./:@-]+$")
    api_key: SecretStr | None = Field(default=None, max_length=4096)
    revision: str = Field(default="", max_length=100)
    dimensions: int = Field(default=1024, ge=1, le=16000)
    send_dimensions: bool = True
    structured_output: Literal["json_schema", "json_object"] = "json_schema"
    vision: bool = True
    enable_thinking: bool | None = None

    @model_validator(mode="after")
    def provider_capabilities(self):
        if self.provider == "siliconflow" and self.enable_thinking is None:
            self.enable_thinking = False
        if self.provider == "deepseek":
            self.structured_output = "json_object"
            if self.enable_thinking is None:
                self.enable_thinking = True
            if self.model == "deepseek-v4-pro":
                self.vision = False
        return self

    @field_validator("base_url")
    @classmethod
    def endpoint(cls, value, info):
        try:
            return validate_model_endpoint(value.strip(), info.data.get("provider"))
        except ModelAPIError as error:
            raise ValueError(str(error)) from None


class ProbeResult(BaseModel):
    status: Literal["ok"]
    answer: str = Field(min_length=1, max_length=500)
