import json

import httpx
import pytest
from app.cli import models as cli
from app.core.config import Settings
from app.services.llm import LLMClient, LLMError
from pydantic import BaseModel, ConfigDict, SecretStr


def settings(**changes):
    return Settings(
        _env_file=None,
        **{
            "llm_api_key": SecretStr("sk-" + "test" * 8),
            "llm_base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "llm_model": "qwen3.8-flash",
            **changes,
        },
    )


def reply(content="LearnFlow LLM OK", **changes):
    return {
        "model": "qwen3.8-flash",
        "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 6},
        **changes,
    }


MESSAGES = [{"role": "user", "content": "Explain linear independence."}]


@pytest.mark.parametrize("thinking", [False, True])
@pytest.mark.parametrize("output_format", ["json_object", "json_schema"])
def test_siliconflow_chat_contract(thinking, output_format):
    class Answer(BaseModel):
        answer: str

    def provider(request):
        assert str(request.url) == "https://api.siliconflow.cn/v1/chat/completions"
        assert request.headers["Authorization"].startswith("Bearer sk-")
        body = json.loads(request.content)
        assert body["max_tokens"] == 512 and "max_completion_tokens" not in body
        assert body["enable_thinking"] is thinking and "thinking" not in body
        assert body["response_format"]["type"] == output_format
        assert body["messages"][-1]["content"][1]["type"] == "image_url"
        assert body["model"] == "siliconflow-vision-fixture"
        result = reply('{"answer":"ok"}', model="siliconflow-vision-fixture")
        result["choices"][0]["message"]["reasoning_content"] = "private reasoning fixture"
        return httpx.Response(200, json=result)

    result = LLMClient(
        settings(
            llm_provider="siliconflow",
            llm_base_url="https://api.siliconflow.cn/v1/",
            llm_model="siliconflow-vision-fixture",
            llm_vision=True,
            llm_structured_output=output_format,
            llm_enable_thinking=thinking,
        ),
        transport=httpx.MockTransport(provider),
    ).complete(
        MESSAGES,
        response_model=Answer,
        max_tokens=512,
        images=[b"\x89PNG\r\n\x1a\nsynthetic image"],
    )
    assert result.parsed.answer == "ok"
    assert "private reasoning" not in result.content


def test_siliconflow_json_mode_merges_system_instructions_and_requires_data_object():
    class Answer(BaseModel):
        answer: str

    messages = [{"role": "system", "content": "Use the fixed test instruction."}, *MESSAGES]
    original = [dict(message) for message in messages]

    def provider(request):
        sent = json.loads(request.content)["messages"]
        assert sum(message["role"] == "system" for message in sent) == 1
        assert "Use the fixed test instruction." in sent[0]["content"]
        assert "Do not return the JSON Schema itself" in sent[0]["content"]
        assert sent[-1] == MESSAGES[-1]
        return httpx.Response(200, json=reply('{"answer":"ok"}'))

    result = LLMClient(
        settings(
            llm_provider="siliconflow",
            llm_base_url="https://api.siliconflow.cn/v1",
            llm_model="fixture",
            llm_structured_output="json_object",
        ),
        transport=httpx.MockTransport(provider),
    ).complete(messages, response_model=Answer)
    assert result.parsed.answer == "ok"
    assert messages == original


def test_page_image_is_attached_to_final_user_message_without_changing_input():
    png = b"\x89PNG\r\n\x1a\n" + b"synthetic image bytes"

    def provider(request):
        payload = json.loads(request.content)
        parts = payload["messages"][-1]["content"]
        assert parts[0] == {"type": "text", "text": MESSAGES[-1]["content"]}
        assert parts[1]["type"] == "image_url"
        assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "extra_body" not in payload
        return httpx.Response(200, json=reply())

    LLMClient(settings(), transport=httpx.MockTransport(provider)).complete(MESSAGES, images=[png])
    assert isinstance(MESSAGES[-1]["content"], str)


def test_non_image_data_is_rejected_before_calling_provider():
    def provider(request):
        pytest.fail("Unexpected provider call")

    with pytest.raises(LLMError, match="PNG and JPEG"):
        LLMClient(settings(), transport=httpx.MockTransport(provider)).complete(
            MESSAGES, images=[b"not an image"]
        )


class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


def test_plain_completion_uses_qwen_request_contract():
    def provider(request):
        assert request.url.path == "/compatible-mode/v1/chat/completions"
        assert (
            request.headers["Authorization"]
            == "Bearer " + settings().llm_api_key.get_secret_value()
        )
        assert json.loads(request.content) == {
            "model": "qwen3.8-flash",
            "messages": MESSAGES,
            "stream": False,
            "enable_thinking": False,
            "max_completion_tokens": 32,
        }
        return httpx.Response(200, json=reply())

    result = LLMClient(settings(), transport=httpx.MockTransport(provider)).complete(
        MESSAGES, max_tokens=32
    )
    assert result.content == "LearnFlow LLM OK"
    assert result.parsed is None
    assert (result.input_tokens, result.output_tokens) == (12, 6)


def test_structured_completion_sends_and_validates_json_schema():
    def provider(request):
        payload = json.loads(request.content)
        assert payload["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "Explanation",
                "strict": True,
                "schema": Explanation.model_json_schema(),
            },
        }
        assert payload["max_completion_tokens"] == settings().llm_max_tokens
        return httpx.Response(200, json=reply('{"answer":"Independent vectors."}'))

    result = LLMClient(settings(), transport=httpx.MockTransport(provider)).complete(
        MESSAGES, response_model=Explanation
    )
    assert result.parsed == Explanation(answer="Independent vectors.")


@pytest.mark.parametrize("thinking", [True, False])
@pytest.mark.parametrize("suffix", ["", "/v1"])
def test_deepseek_json_vision_and_thinking_contract(thinking, suffix):
    def provider(request):
        assert request.url == "https://api.deepseek.com" + suffix + "/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "deepseek-flash"
        assert payload["thinking"] == {"type": "enabled" if thinking else "disabled"}
        assert payload["max_tokens"] == 4096
        assert "enable_thinking" not in payload and "max_completion_tokens" not in payload
        assert payload["response_format"] == {"type": "json_object"}
        assert "JSON" in payload["messages"][0]["content"]
        assert payload["messages"][-1]["content"][1]["type"] == "image_url"
        result = reply('{"answer":"ok"}', model="DeepSeek-V4.1-Flash-1017")
        result["choices"][0]["message"]["reasoning_content"] = "private reasoning"
        return httpx.Response(200, json=result)

    config = settings(
        llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com" + suffix,
        llm_model="deepseek-flash",
        llm_enable_thinking=thinking,
    )
    result = LLMClient(config, transport=httpx.MockTransport(provider)).complete(
        MESSAGES,
        response_model=Explanation,
        max_tokens=4096,
        images=[b"\x89PNG\r\n\x1a\nsynthetic"],
    )
    assert result.parsed == Explanation(answer="ok")
    assert "private reasoning" not in result.content


def test_deepseek_pro_rejects_images_but_allows_text():
    config = settings(
        llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-v4-pro",
        llm_vision=True,
    )
    assert not config.llm_vision
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(200, json=reply(model="DeepSeek-V4-Pro-0813"))

    client = LLMClient(config, transport=httpx.MockTransport(provider))
    with pytest.raises(LLMError) as error:
        client.complete(MESSAGES, images=[b"\x89PNG\r\n\x1a\nsynthetic"])
    assert error.value.code == "vision_unsupported"
    assert not calls
    assert client.complete(MESSAGES).content == "LearnFlow LLM OK"


@pytest.mark.parametrize(
    "content", ["not JSON", '{"other":"value"}', '{"answer":42}', '{"answer":"ok","extra":true}']
)
def test_invalid_structured_output_is_rejected(content):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=reply(content)))
    with pytest.raises(LLMError, match="JSON schema") as error:
        LLMClient(settings(), transport=transport).complete(MESSAGES, response_model=Explanation)
    assert content not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        reply(""),
        reply(None),
        reply(model="other-model"),
        reply(choices=[]),
        reply(
            choices=[
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "reasoning_content": "private reasoning"},
                }
            ]
        ),
        reply(
            choices=[
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "answer", "refusal": "refused"},
                }
            ]
        ),
        reply(usage={"prompt_tokens": True}),
    ],
)
def test_incomplete_or_unexpected_responses_are_rejected(payload):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(LLMError, match="unexpected"):
        LLMClient(settings(), transport=transport).complete(MESSAGES)


@pytest.mark.parametrize(
    "reason, message",
    [
        ("length", "truncated"),
        ("tool_calls", "supported text"),
        ("content_filter", "supported text"),
    ],
)
def test_unfinished_answers_are_not_returned_as_success(reason, message):
    payload = reply(
        choices=[
            {"finish_reason": reason, "message": {"role": "assistant", "content": "partial answer"}}
        ]
    )
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(LLMError, match=message):
        LLMClient(settings(), transport=transport).complete(MESSAGES)


def test_provider_errors_do_not_expose_credentials():
    key = settings().llm_api_key.get_secret_value()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            401, json={"error": {"message": "Incorrect key: " + key, "code": key}}
        )
    )
    with pytest.raises(LLMError, match="HTTP 401") as error:
        LLMClient(settings(), transport=transport).complete(MESSAGES)
    assert key not in str(error.value)
    assert "Incorrect key" not in str(error.value)


def test_timeout_does_not_expose_transport_details():
    def provider(request):
        raise httpx.ReadTimeout("private details", request=request)

    with pytest.raises(LLMError, match="timed out") as error:
        LLMClient(settings(), transport=httpx.MockTransport(provider)).complete(MESSAGES)
    assert "private details" not in str(error.value)


def test_schema_failure_has_a_safe_diagnostic_code():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=reply('{"private":"body"}'))
    )
    with pytest.raises(LLMError) as error:
        LLMClient(settings(), transport=transport).complete(MESSAGES, response_model=Explanation)
    assert error.value.code == "invalid_response"
    assert "private" not in str(error.value)


def test_configure_llm_reuses_credentials_and_preserves_existing_configuration(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    key = "sk-" + "test" * 8
    endpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    existing = (
        "DATABASE_URL=postgresql://existing-database\nEMBEDDING_MODEL=qwen3.7-text-embedding\n"
    )
    target = tmp_path / ".env"
    target.write_text(existing, encoding="utf-8")
    from functools import lru_cache

    @lru_cache
    def configured_settings():
        return settings(embedding_api_key=SecretStr(key), embedding_base_url=endpoint)

    monkeypatch.setattr(cli, "get_settings", configured_settings)
    cli.configure_llm("qwen3.8-flash")
    saved = target.read_text(encoding="utf-8")
    assert saved.startswith(existing)
    assert 'LLM_MODEL="qwen3.8-flash"' in saved
    assert 'LLM_API_KEY="' + key + '"' in saved
    assert 'LLM_BASE_URL="' + endpoint + '"' in saved
    assert 'LLM_ENABLE_THINKING="false"' in saved
    assert key not in capsys.readouterr().out
