import json
from types import SimpleNamespace

import httpx
import pytest
from app.api import account as account_api
from app.core.config import Settings, get_settings
from app.core.model_runtime import model_settings
from app.models import AccountModels, KnowledgeEmbedding, ModelProfile
from app.services import account_index, chat, retrieval
from app.services.account_models import resolve_settings
from app.services.embeddings import EmbeddingBatch, EmbeddingClient
from app.services.llm import LLMClient
from app.services.model_api import ModelAPIError
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_chat import answer_fixture, ask, thread
from test_knowledge import create, payload


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    monkeypatch.setattr(
        get_settings(), "model_encryption_key", SecretStr(Fernet.generate_key().decode())
    )


def config(client, kind="embedding", **changes):
    current = client.get("/api/account/models").json()
    return {
        "expected_version": current["version"],
        "provider": "openai_compatible",
        "base_url": "https://models.example.com/v1",
        "model": "embedding-a" if kind == "embedding" else "chat-a",
        "api_key": "sk-account-private-credential",
        "dimensions": 2,
        "send_dimensions": False,
        "vision": False,
        **changes,
    }


def save(client, kind="embedding", **changes):
    response = client.put(f"/api/account/models/{kind}", json=config(client, kind, **changes))
    assert response.status_code == 200, response.text
    return response.json()


def ids(db_engine, user_id):
    with Session(db_engine) as db:
        account = db.get(AccountModels, user_id)
        return account.embedding_id, account.pending_embedding_id


@pytest.fixture
def embedder(db_engine, monkeypatch):
    monkeypatch.setattr(
        account_index, "SessionLocal", sessionmaker(bind=db_engine, expire_on_commit=False)
    )
    calls = []

    def embed(texts):
        settings = model_settings()
        calls.append((texts, settings))
        return EmbeddingBatch([[1.0, 0.0] for _ in texts], settings.embedding_model, 2, 10)

    monkeypatch.setattr(account_index, "EmbeddingClient", lambda: SimpleNamespace(embed=embed))
    monkeypatch.setattr(retrieval, "EmbeddingClient", lambda: SimpleNamespace(embed=embed))
    return calls


def test_profile_llm_settings_and_secret_encryption(client, account, db_engine):
    original_model = get_settings().llm_model
    assert (
        client.patch("/api/account/profile", json={"name": "  新称呼  "}).json()["name"] == "新称呼"
    )
    assert client.get("/api/auth/me").json()["name"] == "新称呼"
    result = save(client, "llm")
    assert result["llm"]["model"] == "chat-a" and result["llm"]["has_api_key"]
    assert "sk-account" not in json.dumps(result)
    with Session(db_engine) as db:
        profile = db.scalar(select(ModelProfile))
        assert "sk-account" not in profile.encrypted_key
        settings = resolve_settings(db, account["id"])
        assert settings.llm_api_key.get_secret_value() == "sk-account-private-credential"
    assert get_settings().llm_model == original_model
    request = config(client, "llm", api_key=None, model="chat-b")
    assert client.put("/api/account/models/llm", json=request).status_code == 200
    assert client.put("/api/account/models/llm", json=request).status_code == 409
    assert (
        client.put(
            "/api/account/models/llm",
            json=config(client, "llm", api_key=None, base_url="https://another.example.com/v1"),
        ).status_code
        == 400
    )


def test_accounts_have_separate_credentials_and_settings(client, account, db_engine):
    save(client, "llm")
    first_id = account["id"]
    client.post("/api/auth/logout")
    second = client.post(
        "/api/auth/register",
        json={"name": "Other", "email": "second-model@example.com", "password": "other-password"},
    ).json()
    assert client.get("/api/account/models").json()["llm"]["source"] == "system"
    save(client, "llm", model="other-chat", api_key="sk-other-private-credential")
    with Session(db_engine) as db:
        first = resolve_settings(db, first_id)
        other = resolve_settings(db, second["id"])
        assert first.llm_model == "chat-a" and other.llm_model == "other-chat"
        assert first.llm_api_key != other.llm_api_key


@pytest.mark.parametrize("model,vision", [("deepseek-flash", True), ("deepseek-v4-pro", False)])
def test_deepseek_account_settings_defaults_and_runtime(client, account, db_engine, model, vision):
    original_embedding = client.get("/api/account/models").json()["embedding"]
    result = save(
        client,
        "llm",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        model=model,
        vision=True,
    )
    assert result["llm"]["vision"] is vision
    assert result["llm"]["structured_output"] == "json_object"
    assert result["llm"]["enable_thinking"] is True
    assert result["embedding"] == original_embedding
    with Session(db_engine) as db:
        resolved = resolve_settings(db, account["id"])
        assert resolved.llm_provider == "deepseek"
        assert resolved.llm_enable_thinking is True
        assert resolved.llm_vision is vision
    save(
        client,
        "llm",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        model=model,
        api_key=None,
        enable_thinking=False,
    )
    assert client.get("/api/account/models").json()["llm"]["enable_thinking"] is False
    assert "sk-account" not in json.dumps(result)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.deepseek.com/anthropic",
        "https://other.example.com",
        "http://api.deepseek.com",
        "https://api.deepseek.com?key=secret",
    ],
)
def test_deepseek_rejects_wrong_protocol_or_endpoint(client, account, endpoint):
    response = client.put(
        "/api/account/models/llm",
        json=config(client, "llm", provider="deepseek", base_url=endpoint, model="deepseek-flash"),
    )
    assert response.status_code == 422


def test_deepseek_cannot_be_used_as_embedding_provider(client, account):
    request = config(
        client, provider="deepseek", base_url="https://api.deepseek.com", model="deepseek-flash"
    )
    assert client.put("/api/account/models/embedding", json=request).status_code == 422
    assert client.post("/api/account/models/embedding/test", json=request).status_code == 422


@pytest.mark.parametrize(
    "kind,model",
    [("llm", "deepseek-ai/DeepSeek-V4-Flash"), ("embedding", "Qwen/Qwen3-Embedding-8B")],
)
def test_siliconflow_settings_are_encrypted_and_do_not_reuse_other_provider_key(
    client, account, db_engine, kind, model
):
    save(client, kind)
    new = config(
        client,
        kind,
        provider="siliconflow",
        base_url="https://api.siliconflow.cn/v1/",
        model=model,
        api_key=None,
    )
    assert client.put(f"/api/account/models/{kind}", json=new).status_code == 400
    new["api_key"] = "sk-siliconflow-private-fixture"
    response = client.put(f"/api/account/models/{kind}", json=new)
    assert response.status_code == 200, response.text
    result = response.json()
    profile = (
        (result["pending_embedding"] or result["embedding"])
        if kind == "embedding"
        else result["llm"]
    )
    assert profile["provider"] == "siliconflow"
    assert profile["base_url"] == "https://api.siliconflow.cn/v1" and profile["has_api_key"]
    assert "sk-siliconflow" not in json.dumps(result)
    if kind == "llm":
        assert profile["enable_thinking"] is False
    with Session(db_engine) as db:
        matches = [
            row
            for row in db.scalars(select(ModelProfile))
            if row.config["provider"] == "siliconflow"
        ]
        assert len(matches) == 1 and "sk-siliconflow" not in matches[0].encrypted_key


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://api.siliconflow.cn/v1",
        "https://api.siliconflow.cn/v1/embeddings",
        "https://api.siliconflow.cn/v1?key=secret",
        "https://other.example.com/v1",
    ],
)
def test_siliconflow_rejects_wrong_endpoint_before_probe(client, account, endpoint):
    body = config(client, "llm", provider="siliconflow", base_url=endpoint)
    assert client.post("/api/account/models/llm/test", json=body).status_code == 422


@pytest.mark.parametrize(
    "changes,label",
    [
        ({"provider": "unsupported-provider"}, "接口类型"),
        ({"model": "invalid model"}, "模型名称"),
        ({"dimensions": 0}, "向量维度"),
    ],
)
def test_model_validation_identifies_fields_without_echoing_credentials(
    client, account, changes, label
):
    body = config(client, "llm", api_key="sk-fixed-secret-that-must-not-be-echoed", **changes)
    response = client.post("/api/account/models/llm/test", json=body)
    assert response.status_code == 422
    assert label in response.json()["detail"]
    assert body["api_key"] not in response.text


def test_old_account_profile_without_thinking_keeps_system_default(client, account, db_engine):
    save(client, "llm")
    with Session(db_engine) as db:
        profile = db.scalar(select(ModelProfile))
        profile.config = {k: v for k, v in profile.config.items() if k != "enable_thinking"}
        db.commit()
        assert (
            resolve_settings(db, account["id"]).llm_enable_thinking
            == get_settings().llm_enable_thinking
        )
    assert (
        client.get("/api/account/models").json()["llm"]["enable_thinking"]
        == get_settings().llm_enable_thinking
    )


def test_embedding_rebuild_covers_all_courses_and_switches_atomically(
    client, course, account, db_engine, embedder, monkeypatch
):
    first = create(
        client, course, title="Hessian", content="Positive definiteness gives a strict minimum."
    )
    second_course = client.post("/api/courses", json={"name": "Second course"}).json()
    second = create(client, second_course, title="Bread", content="An oven bakes bread.")
    save(client)
    old_id, pending_id = ids(db_engine, account["id"])
    account_index.index_profile(pending_id, [(first["id"], 1)])
    assert ids(db_engine, account["id"]) == (old_id, pending_id)
    progress = client.get("/api/account/models").json()
    assert progress["rebuild"]["ready"] == 1 and progress["rebuild"]["total"] == 2
    account_index.index_profile(pending_id, [(second["id"], 1)])
    assert ids(db_engine, account["id"]) == (pending_id, None)
    assert client.get("/api/account/models").json()["index"]["ready"] == 2
    monkeypatch.setattr(chat, "generate_answer", answer_fixture)
    _, path = thread(client, course)
    message = ask(client, path, "stationarity").json()
    assert message["retrieval_mode"] == "semantic"
    assert message["citations"][0]["knowledge_id"] == first["id"]
    assert embedder[-1][1].embedding_model == "embedding-a"
    save(client, model="embedding-b")
    state = client.get("/api/account/models").json()
    assert state["embedding"]["model"] == "embedding-a"
    assert state["pending_embedding"]["model"] == "embedding-b"
    assert ask(client, path, "stationarity").json()["retrieval_mode"] == "semantic"
    assert embedder[-1][1].embedding_model == "embedding-a"


def test_key_rotation_and_llm_change_preserve_index_but_provider_address_does_not(
    client, course, account, db_engine, embedder
):
    point = create(client, course)
    save(client)
    _, pending_id = ids(db_engine, account["id"])
    account_index.index_profile(pending_id, [(point["id"], 1)])
    save(client, api_key="sk-rotated-private-credential")
    assert ids(db_engine, account["id"]) == (pending_id, None)
    save(client, "llm")
    assert ids(db_engine, account["id"]) == (pending_id, None)
    assert client.get("/api/account/models").json()["index"]["ready"] == 1
    save(client, base_url="https://other.example.com/v1")
    active, pending = ids(db_engine, account["id"])
    assert active == pending_id and pending != active


def test_replaced_pending_job_cannot_write_old_vectors(
    client, course, account, db_engine, embedder, monkeypatch
):
    point = create(client, course)
    save(client)
    _, stale_id = ids(db_engine, account["id"])

    def replace(texts):
        save(client, model="embedding-b")
        return EmbeddingBatch([[1.0, 0.0] for _ in texts], "embedding-a", 2, 10)

    monkeypatch.setattr(account_index, "EmbeddingClient", lambda: SimpleNamespace(embed=replace))
    assert account_index.index_profile(stale_id, [(point["id"], 1)])["indexed"] == 0
    with Session(db_engine) as db:
        assert db.get(ModelProfile, stale_id) is None
        assert db.scalar(select(func.count(KnowledgeEmbedding.chunk_id))) == 0


def test_revision_during_rebuild_is_not_replaced_by_old_vector(
    client, course, account, db_engine, embedder, monkeypatch
):
    point = create(client, course)
    save(client)
    old_id, pending_id = ids(db_engine, account["id"])

    def revise(texts):
        response = client.patch(
            f"/api/courses/{course['id']}/knowledge/{point['id']}",
            json=payload(content="Updated knowledge", expected_version=1, reason="Correction"),
        )
        assert response.status_code == 200
        return EmbeddingBatch([[1.0, 0.0] for _ in texts], "embedding-a", 2, 10)

    monkeypatch.setattr(account_index, "EmbeddingClient", lambda: SimpleNamespace(embed=revise))
    assert account_index.index_profile(pending_id, [(point["id"], 1)])["indexed"] == 0
    assert ids(db_engine, account["id"]) == (old_id, pending_id)
    assert client.get("/api/account/models").json()["rebuild"]["ready"] == 0


def test_failed_new_index_keeps_active_index_and_can_be_cancelled(
    client, course, account, db_engine, embedder, monkeypatch
):
    point = create(client, course)
    save(client)
    _, active_id = ids(db_engine, account["id"])
    account_index.index_profile(active_id, [(point["id"], 1)])
    save(client, model="embedding-b")
    _, pending_id = ids(db_engine, account["id"])

    def fail(texts):
        raise ModelAPIError("private-provider-response-sk-secret")

    monkeypatch.setattr(account_index, "EmbeddingClient", lambda: SimpleNamespace(embed=fail))
    account_index.index_profile(pending_id, [(point["id"], 1)])
    result = client.get("/api/account/models").json()
    assert result["index"]["ready"] == 1 and result["rebuild"]["failed"] == 1
    assert "private-provider" not in json.dumps(result)
    version = client.get("/api/account/models").json()["version"]
    assert (
        client.delete(
            f"/api/account/models/embedding/pending?expected_version={version}"
        ).status_code
        == 200
    )
    assert ids(db_engine, account["id"]) == (active_id, None)
    assert account_index.index_profile(pending_id, [(point["id"], 1)])["indexed"] == 0


def test_llm_runtime_uses_account_model_and_restores_global_context(client, course, monkeypatch):
    create(client, course)
    save(client, "llm")
    observed = []

    def answer(question, history, context):
        observed.append(model_settings().llm_model)
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", answer)
    _, path = thread(client, course)
    assert ask(client, path).status_code == 200
    assert observed == ["chat-a"]
    assert model_settings() is get_settings()


def test_model_probe_only_sends_fixed_text_and_does_not_save_settings(client, account, monkeypatch):
    seen = []

    def provider(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "model": "resolved-chat-version",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"status":"ok","answer":"LearnFlow OK"}',
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(
        account_api, "LLMClient", lambda: LLMClient(transport=httpx.MockTransport(provider))
    )
    response = client.post(
        "/api/account/models/llm/test", json=config(client, "llm", structured_output="json_object")
    )
    assert response.status_code == 200, response.text
    assert seen[0]["model"] == "chat-a"
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert "enable_thinking" not in seen[0] and "max_tokens" in seen[0]
    assert client.get("/api/account/models").json()["llm"]["source"] == "system"


def test_generic_embedding_can_omit_dimensions_parameter_and_accept_model_alias():
    settings = Settings(
        _env_file=None,
        embedding_provider="openai_compatible",
        embedding_base_url="http://localhost:11434/v1",
        embedding_model="local-embedding",
        embedding_dimensions=2,
        embedding_send_dimensions=False,
    )

    def provider(request):
        body = json.loads(request.content)
        assert "dimensions" not in body and "Authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "model": "local-embedding:latest",
                "data": [{"index": 0, "embedding": [1.0, 0.0]}],
            },
        )

    assert (
        EmbeddingClient(settings, transport=httpx.MockTransport(provider))
        .embed(["fixed text"])
        .dimensions
        == 2
    )


def test_account_llm_controls_extraction_and_vision_requirement(
    client, course, pdf_bytes, db_engine, monkeypatch
):
    from app.services import extraction
    from test_extraction import extracted_page, queued
    from test_knowledge import upload

    save(client, "llm", vision=False)
    document = upload(client, course, pdf_bytes)
    result = client.post(f"/api/documents/{document['id']}/extraction").json()
    assert result["status"] == "failed" and "图片识别" in result["error"]
    save(client, "llm", vision=True)
    monkeypatch.setattr(
        extraction, "SessionLocal", sessionmaker(bind=db_engine, expire_on_commit=False)
    )
    monkeypatch.setattr(extraction, "LLMClient", lambda: SimpleNamespace(settings=model_settings()))
    seen = []

    def infer(text, image, number, client):
        seen.append(client.settings.llm_model)
        return SimpleNamespace(
            parsed=extracted_page(),
            model=client.settings.llm_model,
            input_tokens=10,
            output_tokens=20,
        )

    monkeypatch.setattr(extraction, "infer_page", infer)
    extraction.process_document(*queued(db_engine, {**document, "task": result}))
    assert seen == ["chat-a", "chat-a"]


def test_account_llm_is_used_for_proposal_review(client, course, monkeypatch):
    from app.services import proposal_processing
    from test_proposal_review import make_response, suggestion

    save(client, "llm")
    _, _, _, accept_path = suggestion(client, course)
    seen = []

    def review(current, proposed, reason, sources, images, limited):
        seen.append(model_settings().llm_model)
        result = make_response(proposed)
        result.model = model_settings().llm_model
        return result

    monkeypatch.setattr(proposal_processing, "review_proposal", review)
    response = client.post(accept_path, json={"expected_version": 1})
    assert response.status_code == 200, response.text
    assert seen == ["chat-a"]


def test_cancel_rebuild_checks_settings_version(client, course):
    create(client, course)
    state = save(client)
    save(client, "llm")
    response = client.delete(
        f"/api/account/models/embedding/pending?expected_version={state['version']}"
    )
    assert response.status_code == 409
    assert client.get("/api/account/models").json()["pending_embedding"] is not None
