import math
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.core.model_runtime import model_settings
from app.services.model_api import ModelAPIError as EmbeddingError
from app.services.model_api import (
    local_endpoint,
    post_model_json,
    validate_model_endpoint,
)
from app.services.model_api import validate_aliyun_endpoint as validate_aliyun_endpoint  # noqa: PLC0414


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    model: str
    dimensions: int
    total_tokens: int


class EmbeddingClient:
    def __init__(
        self, settings: Settings | None = None, *, transport: httpx.BaseTransport | None = None
    ):
        self.settings = settings or model_settings()
        self.transport = transport

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        settings = self.settings
        if (
            (
                not settings.embedding_api_key.get_secret_value()
                and not local_endpoint(settings.embedding_base_url)
            )
            or not settings.embedding_base_url
            or not settings.embedding_model
        ):
            raise EmbeddingError(
                "Embedding is not configured. Import an API key and endpoint first."
            )
        endpoint = validate_model_endpoint(settings.embedding_base_url, settings.embedding_provider)
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise EmbeddingError("Embedding input must contain non-empty text.")
        vectors = []
        tokens = 0
        with httpx.Client(
            timeout=httpx.Timeout(settings.embedding_timeout_seconds, connect=10),
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            for offset in range(0, len(texts), settings.embedding_batch_size):
                batch = texts[offset : offset + settings.embedding_batch_size]
                payload = post_model_json(
                    client,
                    endpoint,
                    "/embeddings",
                    settings.embedding_api_key,
                    {
                        "model": settings.embedding_model,
                        "input": batch,
                        **(
                            {"dimensions": settings.embedding_dimensions}
                            if settings.embedding_send_dimensions
                            else {}
                        ),
                        "encoding_format": "float",
                    },
                    "Embedding",
                )
                try:
                    if (
                        settings.embedding_provider == "aliyun"
                        and payload.get("model", settings.embedding_model)
                        != settings.embedding_model
                    ):
                        raise ValueError("model mismatch")
                    rows = payload["data"]
                    if (
                        len(rows) != len(batch)
                        or any(
                            not isinstance(item["index"], int) or isinstance(item["index"], bool)
                            for item in rows
                        )
                        or sorted(item["index"] for item in rows) != list(range(len(batch)))
                    ):
                        raise ValueError("invalid embedding indices")
                    rows = sorted(rows, key=lambda item: item["index"])
                    for row in rows:
                        vector = row["embedding"]
                        if (
                            len(vector) != settings.embedding_dimensions
                            or any(
                                isinstance(number, bool)
                                or not isinstance(number, (int, float))
                                or not math.isfinite(number)
                                for number in vector
                            )
                            or not any(number != 0 for number in vector)
                        ):
                            raise ValueError("invalid embedding values")
                        vectors.append([float(number) for number in vector])
                    usage = payload.get("usage", {}).get("total_tokens", 0)
                    if isinstance(usage, int) and not isinstance(usage, bool) and usage >= 0:
                        tokens += usage
                except (KeyError, TypeError, ValueError, AttributeError):
                    raise EmbeddingError(
                        "Embedding response has an unexpected model, shape or vector value."
                    ) from None
        return EmbeddingBatch(
            vectors, settings.embedding_model, settings.embedding_dimensions, tokens
        )
