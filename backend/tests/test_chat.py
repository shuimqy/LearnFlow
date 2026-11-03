from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from app.core.config import Settings, get_settings
from app.models import ChatMessage, Conversation, KnowledgeChunk, KnowledgePoint
from app.models.base import utcnow
from app.schemas.chat import AnswerDraft
from app.schemas.knowledge import KnowledgeUpdate
from app.services import chat, chat_generation, retrieval, vector_index
from app.services.embeddings import EmbeddingBatch
from app.services.knowledge import find_knowledge, update_knowledge
from app.services.knowledge_index import store_embeddings
from app.services.llm import LLMClient
from app.services.model_api import ModelAPIError
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_knowledge import create, payload, upload


def answer_fixture(question, history, context):
    key = context.items[0]["key"]
    parsed = AnswerDraft(
        status="answered",
        answer=f"根据当前知识正文作答 [{key}]。",
        supplement="补充解释来自当前条件的推导。",
        citations=[key],
    )
    return SimpleNamespace(parsed=parsed, model="qwen3.8-flash", input_tokens=100, output_tokens=50)


@pytest.fixture
def model(monkeypatch):
    calls = []

    def generate(question, history, context):
        calls.append((question, history, context))
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", generate)
    return calls


def thread(client, course):
    response = client.post(f"/api/courses/{course['id']}/conversations", json={})
    assert response.status_code == 201
    conversation = response.json()
    return conversation, f"/api/courses/{course['id']}/conversations/{conversation['id']}"


def ask(client, path, content="线性无关的判断条件是什么？", request_id=None):
    return client.post(
        path + "/messages", json={"content": content, "request_id": request_id or str(uuid4())}
    )


def test_course_question_citations_followups_history_and_idempotency(
    client, course, pdf_bytes, model
):
    document = upload(client, course, pdf_bytes)
    point = create(client, course, sources=[{"document_id": document["id"], "page_number": 2}])
    _conversation, path = thread(client, course)
    request_id = str(uuid4())
    response = ask(client, path, request_id=request_id)
    assert response.status_code == 200, response.text
    message = response.json()
    assert message["status"] == "completed" and message["role"] == "assistant"
    assert message["citations"][0]["knowledge_id"] == point["id"]
    assert message["citations"][0]["current"]
    assert message["citations"][0]["sources"][0]["page_number"] == 2
    assert message["citations"][0]["sources"][0]["available"]
    assert message["retrieval_mode"] == "text"
    assert ask(client, path, request_id=request_id).json()["id"] == message["id"]
    assert ask(client, path, "different question", request_id).status_code == 409
    assert len(model) == 1
    assert ask(client, path, "再解释一下这个条件").status_code == 200
    assert [row["role"] for row in model[-1][1]] == ["user", "assistant"]
    messages = client.get(path + "/messages").json()
    assert [row["sequence"] for row in messages] == [1, 2, 3, 4]
    assert len(client.get(path + "/messages?before=3").json()) == 2
    assert (
        client.get(f"/api/courses/{course['id']}/conversations").json()[0]["title"]
        == "线性无关的判断条件是什么？"
    )


def test_no_evidence_does_not_call_model_or_invent_sources(client, course, model):
    _conversation, path = thread(client, course)
    message = ask(client, path).json()
    assert message["status"] == "completed" and not message["citations"]
    assert message["model"] is None
    assert "没有找到足够相关的依据" in message["content"]
    assert model == []


def test_courses_users_and_conversations_are_isolated(client, course, model):
    create(client, course)
    conversation, path = thread(client, course)
    other = client.post("/api/courses", json={"name": "Other course"}).json()
    _other_thread, other_path = thread(client, other)
    assert not ask(client, other_path).json()["citations"]
    assert model == []
    assert (
        client.get(
            f"/api/courses/{other['id']}/conversations/{conversation['id']}/messages"
        ).status_code
        == 404
    )
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={"email": "chat-other@example.com", "name": "Other", "password": "another-password"},
    )
    for endpoint in [
        f"/api/courses/{course['id']}/conversations",
        path + "/messages",
        f"/api/courses/{course['id']}/retrieval/status",
    ]:
        assert client.get(endpoint).status_code == 404
    assert ask(client, path).status_code == 404
    assert client.delete(path).status_code == 404
    assert client.post(f"/api/courses/{course['id']}/retrieval/index").status_code == 404


def test_semantic_retrieval_uses_vectors_without_exact_words(
    client, course, db_engine, monkeypatch, model
):
    monkeypatch.setattr(get_settings(), "embedding_model", "test-embedding")
    monkeypatch.setattr(get_settings(), "embedding_dimensions", 2)
    monkeypatch.setattr(get_settings(), "embedding_api_key", SecretStr("sk-test-credential"))
    monkeypatch.setattr(
        get_settings(), "embedding_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    related = create(
        client, course, title="Hessian", content="Positive definiteness gives a strict minimum."
    )
    unrelated = create(client, course, title="Bread", content="Bake the bread in an oven.")
    with Session(db_engine) as db:
        store_embeddings(db, related["id"], 1, [[1.0, 0.0]], "test-embedding")
        store_embeddings(db, unrelated["id"], 1, [[0.0, 1.0]], "test-embedding")
        db.commit()
    monkeypatch.setattr(
        retrieval,
        "EmbeddingClient",
        lambda: SimpleNamespace(
            embed=lambda texts: EmbeddingBatch([[1.0, 0.0]], "test-embedding", 2, 10)
        ),
    )
    _conversation, path = thread(client, course)
    response = ask(client, path, "stationarity")
    assert response.status_code == 200, response.text
    assert response.json()["retrieval_mode"] == "semantic"
    assert [citation["knowledge_id"] for citation in response.json()["citations"]] == [
        related["id"]
    ]


def test_old_chunks_and_archived_points_are_never_retrieved(client, course, db_engine, model):
    point = create(client, course, title="Topic", content="retiredword")
    url = f"/api/courses/{course['id']}/knowledge/{point['id']}"
    assert (
        client.patch(
            url,
            json=payload(
                title="Topic", content="currentword", expected_version=1, reason="Replace old text"
            ),
        ).status_code
        == 200
    )
    with Session(db_engine) as db:
        db.add(
            KnowledgeChunk(
                course_id=course["id"],
                knowledge_id=point["id"],
                version=1,
                position=0,
                text="retiredword",
                content_hash="old",
                embedding_status="pending",
            )
        )
        db.commit()
    _conversation, path = thread(client, course)
    assert not ask(client, path, "retiredword").json()["citations"]
    assert client.delete(url + "?expected_version=2").status_code == 204
    assert not ask(client, path, "currentword").json()["citations"]
    assert model == []


def test_failed_answer_can_retry_without_duplicate_messages(client, course, monkeypatch, model):
    create(client, course)
    _conversation, path = thread(client, course)

    def fail(*args):
        raise ModelAPIError("private provider and credential details")

    monkeypatch.setattr(chat, "generate_answer", fail)
    request_id = str(uuid4())
    response = ask(client, path, request_id=request_id)
    assert response.status_code == 502
    assert "private" not in response.text
    messages = client.get(path + "/messages").json()
    assert len(messages) == 2 and messages[-1]["status"] == "failed"
    assert not messages[-1]["content"] and "private" not in messages[-1]["error"]
    monkeypatch.setattr(chat, "generate_answer", answer_fixture)
    assert ask(client, path, request_id=request_id).status_code == 200
    assert len(client.get(path + "/messages").json()) == 2


def test_invalid_model_citations_do_not_get_saved_as_answer(client, course, monkeypatch):
    create(client, course)
    _conversation, path = thread(client, course)
    invalid = AnswerDraft(
        status="answered", answer="Unsupported claim [K999]", supplement="", citations=["K999"]
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "qwen3.8-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": invalid.model_dump_json()},
                    }
                ],
            },
        )
    )
    settings = Settings(
        _env_file=None,
        llm_api_key=SecretStr("sk-test-credential"),
        llm_model="qwen3.8-flash",
        llm_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    monkeypatch.setattr(
        chat_generation, "LLMClient", lambda: LLMClient(settings, transport=transport)
    )
    assert ask(client, path).status_code == 502
    message = client.get(path + "/messages").json()[-1]
    assert message["status"] == "failed" and not message["citations"] and not message["content"]


def test_edit_during_generation_invalidates_answer_then_retry_uses_latest_version(
    client, course, account, db_engine, monkeypatch
):
    point = create(client, course)
    _conversation, path = thread(client, course)

    def edit(question, history, context):
        with Session(db_engine) as db:
            current = find_knowledge(db, course["id"], point["id"])
            update_knowledge(
                db,
                current,
                account["id"],
                KnowledgeUpdate(
                    **payload(
                        content="最新定义：零线性组合的系数只能全为零。",
                        expected_version=1,
                        reason="Correct definition",
                    )
                ),
            )
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", edit)
    request_id = str(uuid4())
    assert ask(client, path, request_id=request_id).status_code == 409
    assert client.get(path + "/messages").json()[-1]["status"] == "failed"
    monkeypatch.setattr(chat, "generate_answer", answer_fixture)
    message = ask(client, path, request_id=request_id).json()
    assert message["citations"][0]["version"] == 2
    assert "最新定义" in message["citations"][0]["text"]


def test_duplicate_inflight_request_and_delete_are_blocked(client, course, monkeypatch):
    create(client, course)
    _conversation, path = thread(client, course)
    request_id = str(uuid4())

    def running(question, history, context):
        assert ask(client, path, request_id=request_id).status_code == 409
        assert client.delete(path).status_code == 409
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", running)
    assert ask(client, path, request_id=request_id).status_code == 200


def test_historical_citations_preserve_snapshot_and_mark_updates_and_deleted_files(
    client, course, pdf_bytes, model
):
    document = upload(client, course, pdf_bytes)
    point = create(client, course, sources=[{"document_id": document["id"], "page_number": 1}])
    _conversation, path = thread(client, course)
    answer = ask(client, path).json()
    before = answer["citations"][0]["text"]
    assert client.delete(f"/api/documents/{document['id']}").status_code == 204
    assert (
        client.patch(
            f"/api/courses/{course['id']}/knowledge/{point['id']}",
            json=payload(content="Revised definition", expected_version=1, reason="Correction"),
        ).status_code
        == 200
    )
    citation = client.get(path + "/messages").json()[-1]["citations"][0]
    assert citation["text"] == before and citation["version"] == 1
    assert not citation["current"] and not citation["sources"][0]["available"]


def test_interrupted_generation_recovers_and_conversation_delete_cascades(
    client, course, db_engine, model
):
    create(client, course)
    conversation, path = thread(client, course)
    answer = ask(client, path).json()
    with Session(db_engine) as db:
        stored = db.get(Conversation, conversation["id"])
        stored.processing_token, stored.processing_started_at = (
            "interrupted",
            utcnow() - timedelta(minutes=6),
        )
        db.get(ChatMessage, answer["id"]).status = "generating"
        db.commit()
    assert client.get(path + "/messages").json()[-1]["status"] == "failed"
    assert client.delete(path).status_code == 204
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(ChatMessage.id))) == 0
        assert db.scalar(select(func.count(KnowledgePoint.id))) == 1


def test_course_deleted_during_model_call_cannot_be_recreated(
    client, course, monkeypatch, db_engine
):
    create(client, course)
    _conversation, path = thread(client, course)

    def deleting(question, history, context):
        assert client.delete(f"/api/courses/{course['id']}").status_code == 204
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", deleting)
    assert ask(client, path).status_code == 404
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(ChatMessage.id))) == 0


def test_index_batch_is_idempotent_and_records_model_dimensions(
    client, course, db_engine, monkeypatch
):
    point = create(client, course)
    monkeypatch.setattr(
        vector_index, "SessionLocal", sessionmaker(bind=db_engine, expire_on_commit=False)
    )
    calls = []

    def embed(texts):
        calls.extend(texts)
        return EmbeddingBatch([[1.0, 0.0] for _ in texts], "test-embedding", 2, 10)

    monkeypatch.setattr(get_settings(), "embedding_model", "test-embedding")
    monkeypatch.setattr(get_settings(), "embedding_dimensions", 2)
    monkeypatch.setattr(vector_index, "configured", lambda: True)
    monkeypatch.setattr(vector_index, "EmbeddingClient", lambda: SimpleNamespace(embed=embed))
    assert vector_index.index_entries([(point["id"], 1)])["indexed"] == 1
    assert vector_index.index_entries([(point["id"], 1)])["indexed"] == 0
    assert len(calls) == 1
    with Session(db_engine) as db:
        chunk = db.scalar(select(KnowledgeChunk))
        assert chunk.embedding_dimensions == 2 and chunk.embedding_status == "ready"


def test_stale_embedding_write_and_model_failure_keep_current_chunks_safe(
    client, course, db_engine, monkeypatch
):
    point = create(client, course)
    monkeypatch.setattr(
        vector_index, "SessionLocal", sessionmaker(bind=db_engine, expire_on_commit=False)
    )
    monkeypatch.setattr(vector_index, "configured", lambda: True)

    def edit_then_embed(texts):
        assert (
            client.patch(
                f"/api/courses/{course['id']}/knowledge/{point['id']}",
                json=payload(
                    content="A new current version", expected_version=1, reason="Correction"
                ),
            ).status_code
            == 200
        )
        return EmbeddingBatch([[1.0, 0.0] for _ in texts], "test-embedding", 2, 10)

    monkeypatch.setattr(
        vector_index, "EmbeddingClient", lambda: SimpleNamespace(embed=edit_then_embed)
    )
    assert vector_index.index_entries([(point["id"], 1)])["indexed"] == 0
    with Session(db_engine) as db:
        assert db.scalar(select(KnowledgeChunk)).embedding is None

    def fail(texts):
        raise ModelAPIError("private provider details")

    monkeypatch.setattr(vector_index, "EmbeddingClient", lambda: SimpleNamespace(embed=fail))
    assert vector_index.index_entries([(point["id"], 2)])["failed"] == 1
    with Session(db_engine) as db:
        chunk = db.scalar(select(KnowledgeChunk))
        assert chunk.embedding_status == "failed" and "private" not in chunk.embedding_error


def test_only_committed_knowledge_changes_enqueue_vectors(
    client, course, monkeypatch, db_engine, account
):
    captured = []
    monkeypatch.setattr(get_settings(), "embedding_auto_index", True)
    monkeypatch.setattr(vector_index, "enqueue_index", lambda entries: captured.extend(entries))
    point = create(client, course)
    assert captured == [(point["id"], 1)]
    with Session(db_engine) as db:
        current = find_knowledge(db, course["id"], point["id"])
        current.content, current.version = "Uncommitted revision", 2
        from app.services.knowledge import save_revision

        save_revision(db, current, account["id"], "update", "Rollback test")
        db.rollback()
    assert captured == [(point["id"], 1)]
