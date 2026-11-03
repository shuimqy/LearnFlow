import base64
import json
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.model_runtime import model_settings
from app.services.model_api import ModelAPIError as LLMError
from app.services.model_api import local_endpoint, post_model_json, validate_model_endpoint


@dataclass(frozen=True)
class LLMResponse:
    model: str
    content: str
    parsed: BaseModel | None
    input_tokens: int
    output_tokens: int


class LLMClient:
    def __init__(
        self, settings: Settings | None = None, *, transport: httpx.BaseTransport | None = None
    ):
        self.settings = settings or model_settings()
        self.transport = transport

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        images: list[bytes] | None = None,
    ) -> LLMResponse:
        settings = self.settings
        if (
            (
                not settings.llm_api_key.get_secret_value()
                and not local_endpoint(settings.llm_base_url)
            )
            or not settings.llm_base_url
            or not settings.llm_model
        ):
            raise LLMError("LLM is not configured. Import an API key and endpoint first.")
        endpoint = validate_model_endpoint(settings.llm_base_url, settings.llm_provider)
        if not messages or any(
            not isinstance(message, dict)
            or message.get("role") not in {"system", "user", "assistant"}
            or not isinstance(message.get("content"), str)
            or not message["content"].strip()
            or set(message) != {"role", "content"}
            for message in messages
        ):
            raise LLMError("LLM input must contain text messages with a valid role.")
        output_limit = settings.llm_max_tokens if max_tokens is None else max_tokens
        if (
            isinstance(output_limit, bool)
            or not isinstance(output_limit, int)
            or not 1 <= output_limit <= 32768
        ):
            raise LLMError("LLM output limit must be between 1 and 32768 tokens.")
        request_messages = [dict(message) for message in messages]
        if images:
            if not settings.llm_vision or (
                settings.llm_provider == "deepseek" and settings.llm_model == "deepseek-v4-pro"
            ):
                raise LLMError(
                    "当前账号的 LLM 未启用图片识别，请在账号设置中更换或启用支持图片的模型。",
                    code="vision_unsupported",
                )
            if len(images) > 4 or request_messages[-1]["role"] != "user":
                raise LLMError("Images require a final user message and at most four images.")
            parts = [{"type": "text", "text": request_messages[-1]["content"]}]
            for data in images:
                if not isinstance(data, bytes) or len(data) > 8 * 1024 * 1024:
                    raise LLMError("Each image must contain at most 8 MB of PNG or JPEG data.")
                mime = (
                    "image/png"
                    if data.startswith(b"\x89PNG\r\n\x1a\n")
                    else "image/jpeg"
                    if data.startswith(b"\xff\xd8\xff")
                    else None
                )
                if mime is None:
                    raise LLMError("Only PNG and JPEG images are supported.")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
                        },
                    }
                )
            request_messages[-1]["content"] = parts
        body = {
            "model": settings.llm_model,
            "messages": request_messages,
            "stream": False,
            (
                "max_completion_tokens" if settings.llm_provider == "aliyun" else "max_tokens"
            ): output_limit,
        }
        if settings.llm_provider in {"aliyun", "siliconflow"}:
            body["enable_thinking"] = settings.llm_enable_thinking
        elif settings.llm_provider == "deepseek":
            body["thinking"] = {"type": "enabled" if settings.llm_enable_thinking else "disabled"}
        if response_model is not None:
            if (
                settings.llm_provider == "deepseek"
                or settings.llm_structured_output == "json_object"
            ):
                body["response_format"] = {"type": "json_object"}
                instruction = (
                    "Return a JSON data object that satisfies the schema below. "
                    "Do not return the JSON Schema itself, Markdown, or an explanation. "
                    "Use the field names defined in properties as the keys of your answer.\nJSON Schema: "
                    + json.dumps(response_model.model_json_schema(), ensure_ascii=False)
                )
                if settings.llm_provider == "siliconflow":
                    # 部分兼容模型会忽略多条 system 消息，约束与原指令合并后发送。
                    systems = [
                        message["content"]
                        for message in request_messages
                        if message["role"] == "system"
                    ]
                    body["messages"] = [
                        {"role": "system", "content": "\n\n".join([*systems, instruction])},
                        *[message for message in request_messages if message["role"] != "system"],
                    ]
                else:
                    request_messages.insert(0, {"role": "system", "content": instruction})
            else:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "strict": True,
                        "schema": response_model.model_json_schema(),
                    },
                }
        with httpx.Client(
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10),
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            payload = post_model_json(
                client, endpoint, "/chat/completions", settings.llm_api_key, body, "LLM"
            )
        try:
            if (
                settings.llm_provider == "aliyun"
                and payload.get("model", settings.llm_model) != settings.llm_model
            ):
                raise ValueError("model mismatch")
            choices = payload["choices"]
            if len(choices) != 1:
                raise ValueError("unexpected number of choices")
            choice = choices[0]
            if choice.get("finish_reason") == "length":
                raise LLMError(
                    "LLM output was truncated. Increase the output token limit.", code="truncated"
                )
            if choice.get("finish_reason") != "stop":
                raise LLMError("LLM did not finish a supported text response.")
            message = choice["message"]
            content = message["content"]
            if (
                message.get("role") != "assistant"
                or message.get("refusal")
                or not isinstance(content, str)
                or not content.strip()
            ):
                raise ValueError("empty response or refusal")
            parsed = (
                response_model.model_validate_json(content) if response_model is not None else None
            )
            usage = payload.get("usage", {})
            input_tokens, output_tokens = (
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in [input_tokens, output_tokens]
            ):
                raise ValueError("invalid usage")
            return LLMResponse(settings.llm_model, content, parsed, input_tokens, output_tokens)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError, ValidationError):
            raise LLMError(
                "LLM response has an unexpected model, message or JSON schema.",
                code="invalid_response",
            ) from None
