from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://learnflow:learnflow_local@127.0.0.1:5432/learnflow"
    test_database_url: str | None = None
    manage_local_postgres: bool = False
    redis_url: str = "redis://localhost:6379/0"
    storage_path: Path = ROOT / "storage"
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    cookie_secure: bool = False
    max_upload_mb: int = 25
    session_days: int = 14
    model_encryption_key: SecretStr = SecretStr("")
    llm_provider: str = "aliyun"
    llm_structured_output: str = "json_schema"
    llm_vision: bool = True
    embedding_provider: str = "aliyun"
    embedding_revision: str = ""
    embedding_send_dimensions: bool = True
    embedding_api_key: SecretStr = SecretStr("")
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = Field(default=1024, ge=1, le=16000)
    embedding_batch_size: int = Field(default=20, ge=1, le=20)
    embedding_timeout_seconds: float = Field(default=30, gt=0, le=120)
    embedding_auto_index: bool = True
    rag_min_similarity: float = Field(default=0.45, ge=0, le=1)
    chat_max_tokens: int = Field(default=4096, ge=512, le=16384)
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_model: str = ""
    llm_max_tokens: int = Field(default=2048, ge=1, le=32768)
    llm_enable_thinking: bool = False
    llm_timeout_seconds: float = Field(default=60, gt=0, le=180)
    extraction_auto_start: bool = True
    document_auto_organize: bool = True
    extraction_max_pages: int = Field(default=300, ge=1, le=2000)
    extraction_max_tokens: int = Field(default=8192, ge=1024, le=32768)

    @model_validator(mode="after")
    def llm_capabilities(self):
        if self.llm_provider == "deepseek":
            self.llm_structured_output = "json_object"
            if self.llm_model == "deepseek-v4-pro":
                self.llm_vision = False
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
