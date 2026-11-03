import json

import httpx
import pytest
from app.cli import models as cli
from app.core.config import Settings
from app.services.embeddings import EmbeddingClient, EmbeddingError, validate_aliyun_endpoint
from pydantic import SecretStr


def settings(**changes):
    return Settings(
        _env_file=None,
        **{
            "embedding_api_key": SecretStr("sk-" + "test" * 8),
            "embedding_base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "embedding_model": "qwen3.7-text-embedding",
            "embedding_dimensions": 2,
            **changes,
        },
    )


@pytest.mark.parametrize(
    "model,dimensions,send",
    [
        ("Qwen/Qwen3-Embedding-8B", 64, True),
        ("BAAI/bge-m3", 1024, False),
    ],
)
def test_siliconflow_embedding_contract(model, dimensions, send):
    def provider(request):
        assert str(request.url) == "https://api.siliconflow.cn/v1/embeddings"
        assert request.headers["Authorization"].startswith("Bearer sk-")
        body = json.loads(request.content)
        assert body["model"] == model and body["input"] == ["固定样本一", "固定样本二"]
        assert body["encoding_format"] == "float"
        if send:
            assert body["dimensions"] == dimensions
        else:
            assert "dimensions" not in body
        return httpx.Response(
            200,
            json={
                "model": model,
                "data": [
                    {"index": 1, "embedding": [2.0] * dimensions},
                    {"index": 0, "embedding": [1.0] * dimensions},
                ],
                "usage": {"total_tokens": 8},
            },
        )

    result = EmbeddingClient(
        settings(
            embedding_provider="siliconflow",
            embedding_base_url="https://api.siliconflow.cn/v1/",
            embedding_model=model,
            embedding_dimensions=dimensions,
            embedding_send_dimensions=send,
        ),
        transport=httpx.MockTransport(provider),
    ).embed(["固定样本一", "固定样本二"])
    assert result.vectors == [[1.0] * dimensions, [2.0] * dimensions]
    assert result.total_tokens == 8


def test_batches_and_reordered_results_preserve_input_order():
    calls = []

    def provider(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert (
            request.headers["Authorization"]
            == "Bearer " + settings().embedding_api_key.get_secret_value()
        )
        assert payload["encoding_format"] == "float"
        assert payload["model"] == "qwen3.7-text-embedding"
        rows = [
            {"index": i, "embedding": [float(text), 1.0]} for i, text in enumerate(payload["input"])
        ]
        return httpx.Response(
            200,
            json={
                "model": payload["model"],
                "data": list(reversed(rows)),
                "usage": {"total_tokens": len(rows)},
            },
        )

    client = EmbeddingClient(
        settings(embedding_batch_size=2), transport=httpx.MockTransport(provider)
    )
    result = client.embed(["1", "2", "3"])
    assert len(calls) == 2
    assert [vector[0] for vector in result.vectors] == [1.0, 2.0, 3.0]
    assert result.total_tokens == 3


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"index": 0, "embedding": [1.0]}],
        [{"index": True, "embedding": [1.0, 2.0]}],
        [{"index": 0, "embedding": [0.0, 0.0]}],
        [{"index": 0, "embedding": [True, 2.0]}],
        [{"index": 0, "embedding": ["1", 2.0]}],
    ],
)
def test_malformed_vectors_are_rejected(rows):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": rows}))
    with pytest.raises(EmbeddingError, match="unexpected"):
        EmbeddingClient(settings(), transport=transport).embed(["知识点"])


@pytest.mark.parametrize("code", ["invalid_api_key", "sk-" + "test" * 8])
def test_provider_errors_never_echo_credentials(code):
    key = settings().embedding_api_key.get_secret_value()
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            401,
            json={
                "error": {
                    "message": "Incorrect API key: " + key,
                    "code": code,
                }
            },
        )
    )
    with pytest.raises(EmbeddingError) as error:
        EmbeddingClient(settings(), transport=transport).embed(["测试"])
    assert "401" in str(error.value)
    assert key not in str(error.value)


def test_redirects_are_not_followed():
    urls = []

    def redirect(request):
        urls.append(str(request.url))
        return httpx.Response(307, headers={"Location": "https://other.example/embeddings"})

    with pytest.raises(EmbeddingError, match="HTTP 307"):
        EmbeddingClient(settings(), transport=httpx.MockTransport(redirect)).embed(["测试"])
    assert len(urls) == 1


def test_timeouts_are_reported_without_request_details():
    def timeout(request):
        raise httpx.ReadTimeout("private transport details", request=request)

    with pytest.raises(EmbeddingError, match="timed out") as error:
        EmbeddingClient(settings(), transport=httpx.MockTransport(timeout)).embed(["测试"])
    assert "private transport" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "http://dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope.aliyuncs.com.other.example/compatible-mode/v1",
        "https://user:password@dashscope.aliyuncs.com/compatible-mode/v1",
        "https://dashscope.aliyuncs.com/compatible-mode/v1?key=secret",
    ],
)
def test_untrusted_csv_endpoints_are_rejected(url):
    with pytest.raises(EmbeddingError):
        validate_aliyun_endpoint(url)


def test_csv_import_preserves_database_configuration_and_masks_output(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    target = tmp_path / ".env"
    target.write_text(
        "DATABASE_URL=postgresql://existing-database\nEMBEDDING_MODEL=old-model\n", encoding="utf-8"
    )
    key = "sk-" + "test" * 8
    csv = tmp_path / "credentials.csv"
    csv.write_text(
        "id,1\napiKey,"
        + key
        + "\nopenAiCompatible,https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1\n",
        encoding="utf-8-sig",
    )
    cli.configure_embedding(csv, "qwen3.7-text-embedding", 1024)
    saved = target.read_text(encoding="utf-8")
    assert "DATABASE_URL=postgresql://existing-database" in saved
    assert saved.count("EMBEDDING_MODEL=") == 1
    assert key in saved
    assert key not in capsys.readouterr().out


def test_duplicate_env_configuration_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    content = "EMBEDDING_MODEL=one\nEMBEDDING_MODEL=two\n"
    (tmp_path / ".env").write_text(content, encoding="utf-8")
    csv = tmp_path / "credentials.csv"
    csv.write_text(
        "apiKey,sk-"
        + "test" * 8
        + "\nopenAiCompatible,https://dashscope.aliyuncs.com/compatible-mode/v1\n",
        encoding="utf-8",
    )
    with pytest.raises(EmbeddingError, match="Duplicate"):
        cli.configure_embedding(csv, "qwen3.7-text-embedding", 1024)
    assert (tmp_path / ".env").read_text(encoding="utf-8") == content
