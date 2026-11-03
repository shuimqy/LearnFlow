from uuid import uuid4

import pytest
from app.models import ChatGraphThread, ChatMessage, Conversation
from app.services import chat
from app.services.chat_checkpoints import conversation_checkpointer, thread_id
from app.services.chat_graph import build_chat_graph
from app.services.model_api import ModelAPIError
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_chat import answer_fixture, ask, thread
from test_knowledge import create, payload


@pytest.fixture
def model(monkeypatch):
    calls = []

    def generate(question, history, context):
        calls.append((question, history, context))
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", generate)
    return calls


def branch_payload(answer, **changes):
    return {
        "request_id": str(uuid4()),
        "parent_message_id": answer["id"],
        "question": "线性无关这个条件为什么成立？",
        "anchor_text": "当前知识正文",
        "context_mode": "focused",
        **changes,
    }


def fork(client, path, answer, **changes):
    body = branch_payload(answer, **changes)
    result = client.post(path + "/branches", json=body)
    assert result.status_code == 201, result.text
    row = result.json()
    return row, path.rsplit("/", 1)[0] + "/" + row["id"], body


def checkpoint_counts(db):
    return [
        db.scalar(text(f"SELECT count(*) FROM {table}"))
        for table in ("chat_graph_threads", "checkpoints", "checkpoint_blobs", "checkpoint_writes")
    ]


def test_graph_state_survives_new_saver_and_is_physically_deleted(
    client, course, account, db_engine, model
):
    create(client, course)
    conversation, path = thread(client, course)
    message = ask(client, path).json()
    assert message["workflow_stage"] == "completed"
    identity = thread_id(account["id"], course["id"], conversation["id"])
    with Session(db_engine) as db:
        owner = db.get(ChatGraphThread, identity)
        with conversation_checkpointer(db, identity, owner.run_id) as saver:
            state = build_chat_graph(saver).get_state({"configurable": {"thread_id": identity}})
        assert state.values["saved"] is True and not state.next
        assert state.values["question"] == "线性无关的判断条件是什么？"
        assert state.values["answer"]["answer"] == message["content"]
        assert all(count > 0 for count in checkpoint_counts(db))
    assert client.delete(path).status_code == 204
    with Session(db_engine) as db:
        assert checkpoint_counts(db) == [0, 0, 0, 0]


def test_checkpoint_errors_never_store_private_provider_body(
    client, course, db_engine, monkeypatch
):
    create(client, course)
    _root, path = thread(client, course)
    private = "sk-private-provider-error-12345"

    def fail(*args):
        raise ModelAPIError(private)

    monkeypatch.setattr(chat, "generate_answer", fail)
    request_id = str(uuid4())
    assert ask(client, path, request_id=request_id).status_code == 502
    with Session(db_engine) as db:
        errors = (
            db.execute(text("SELECT blob FROM checkpoint_writes WHERE channel = '__error__'"))
            .scalars()
            .all()
        )
        assert errors and all(private.encode() not in bytes(blob) for blob in errors)
    monkeypatch.setattr(chat, "generate_answer", answer_fixture)
    assert ask(client, path, request_id=request_id).status_code == 200


def test_branch_creation_idempotency_pending_first_answer_and_root_history(client, course, model):
    create(client, course)
    root, path = thread(client, course)
    answer = ask(client, path).json()
    before = client.get(path + "/messages").json()
    branch, branch_path, body = fork(client, path, answer)
    assert branch["parent_conversation_id"] == root["id"]
    assert branch["source_question"] == before[0]["content"]
    assert branch["anchor_text"] == body["anchor_text"]
    assert client.post(path + "/branches", json=body).json()["id"] == branch["id"]
    assert client.post(path + "/branches", json={**body, "question": "另一问题"}).status_code == 409
    pending = client.get(branch_path + "/messages").json()
    assert len(pending) == 2 and pending[-1]["status"] == "pending"
    assert ask(client, branch_path, "不能跳过首个问题").status_code == 409
    assert len(model) == 1
    first = ask(client, branch_path, body["question"], body["request_id"])
    assert first.status_code == 200, first.text
    assert (
        ask(client, branch_path, body["question"], body["request_id"]).json()["id"]
        == first.json()["id"]
    )
    assert len(model) == 2
    assert len(client.get(branch_path + "/messages").json()) == 2
    assert client.get(path + "/messages").json() == before
    assert [row["id"] for row in client.get(path.rsplit("/", 1)[0]).json()] == [root["id"]]
    assert client.get(branch_path).json()["id"] == branch["id"]
    assert client.get(path + "/branches").json()[0]["id"] == branch["id"]


@pytest.mark.parametrize("mode", ["focused", "full", "minimal"])
def test_branch_snapshot_is_immutable_and_main_branch_checkpoints_are_independent(
    client, course, db_engine, model, mode
):
    create(client, course)
    root, path = thread(client, course)
    assert ask(client, path, "之前的线性无关问题").status_code == 200
    answer = ask(client, path).json()
    branch, branch_path, body = fork(client, path, answer, context_mode=mode)
    assert ask(client, path, "创建分支之后新增的线性无关问题").status_code == 200
    assert ask(client, branch_path, body["question"], body["request_id"]).status_code == 200
    history = model[-1][1]
    inherited = "\n".join(row["content"] for row in history)
    assert body["anchor_text"] in inherited
    assert "创建分支之后新增" not in inherited
    assert "[K1]" not in inherited
    assert ("之前的线性无关问题" in inherited) == (mode != "minimal")
    assert ask(client, branch_path, "继续解释线性无关条件").status_code == 200
    assert body["question"] in "\n".join(row["content"] for row in model[-1][1])
    assert len(client.get(path + "/messages").json()) == 6
    assert len(client.get(branch_path + "/messages").json()) == 4
    with Session(db_engine) as db:
        threads = db.scalars(select(ChatGraphThread)).all()
        assert len(threads) == 2 and len({row.thread_id for row in threads}) == 2
        assert {row.conversation_id for row in threads} == {root["id"], branch["id"]}


def test_long_branch_context_is_bounded_and_reports_truncation(client, course, db_engine, model):
    create(client, course)
    _root, path = thread(client, course)
    answer = ask(client, path).json()
    with Session(db_engine) as db:
        row = db.get(ChatMessage, answer["id"])
        row.content, row.supplement = "定义。" * 8000, "推导。" * 3000
        db.commit()
    branch, _branch_path, _body = fork(client, path, answer, anchor_text="", context_mode="full")
    assert branch["context_truncated"] and len(branch["anchor_text"]) == 6000
    with Session(db_engine) as db:
        snapshot = db.get(Conversation, branch["id"]).context_snapshot
        assert len(snapshot["parent_answer"]) == 24000
        assert sum(len(row["content"]) for row in snapshot["messages"]) <= 32000


def test_branches_retrieve_current_knowledge_and_show_workflow_stage(client, course, monkeypatch):
    point = create(client, course)
    _root, path = thread(client, course)
    monkeypatch.setattr(chat, "generate_answer", answer_fixture)
    answer = ask(client, path).json()
    _branch, branch_path, body = fork(client, path, answer)
    assert (
        client.patch(
            f"/api/courses/{course['id']}/knowledge/{point['id']}",
            json=payload(content="线性无关的最新定义。", expected_version=1, reason="修正定义"),
        ).status_code
        == 200
    )

    def generate(question, history, context):
        rows = client.get(branch_path + "/messages").json()
        assert rows[-1]["status"] == "generating" and rows[-1]["workflow_stage"] == "generating"
        assert context.items[0]["version"] == 2
        assert "最新定义" in context.items[0]["text"]
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", generate)
    result = ask(client, branch_path, body["question"], body["request_id"])
    assert result.status_code == 200, result.text
    assert result.json()["citations"][0]["version"] == 2


def test_branch_source_course_user_isolation_and_no_nested_branches(client, course, model):
    create(client, course)
    _root, path = thread(client, course)
    answer = ask(client, path).json()
    _other_root, other_path = thread(client, course)
    assert client.post(other_path + "/branches", json=branch_payload(answer)).status_code == 404
    user_message = client.get(path + "/messages").json()[0]
    assert client.post(path + "/branches", json=branch_payload(user_message)).status_code == 404
    branch, branch_path, body = fork(client, path, answer)
    assert ask(client, branch_path, body["question"], body["request_id"]).status_code == 200
    branch_answer = client.get(branch_path + "/messages").json()[-1]
    assert (
        client.post(branch_path + "/branches", json=branch_payload(branch_answer)).status_code
        == 400
    )
    other_course = client.post("/api/courses", json={"name": "另一门课"}).json()
    assert (
        client.get(f"/api/courses/{other_course['id']}/conversations/{branch['id']}").status_code
        == 404
    )
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={"email": "branch-other@example.com", "name": "Other", "password": "another-password"},
    )
    for endpoint in (path + "/branches", branch_path, branch_path + "/messages"):
        assert client.get(endpoint).status_code == 404
    assert client.post(path + "/branches", json=body).status_code == 404
    assert ask(client, branch_path).status_code == 404
    assert client.delete(branch_path).status_code == 404


@pytest.mark.parametrize("delete_course", [False, True])
def test_deletion_cascades_branch_snapshots_messages_and_checkpoints(
    client, course, db_engine, model, delete_course
):
    create(client, course)
    _root, path = thread(client, course)
    answer = ask(client, path).json()
    _branch, branch_path, body = fork(client, path, answer)
    assert ask(client, branch_path, body["question"], body["request_id"]).status_code == 200
    assert (
        client.delete(f"/api/courses/{course['id']}" if delete_course else path).status_code == 204
    )
    assert client.get(branch_path).status_code == 404
    with Session(db_engine) as db:
        assert checkpoint_counts(db) == [0, 0, 0, 0]
        assert db.scalars(select(Conversation)).all() == []
        assert db.scalars(select(ChatMessage)).all() == []


def test_deleting_branch_keeps_root_and_root_delete_during_generation_cannot_resurrect(
    client, course, db_engine, monkeypatch, model
):
    create(client, course)
    _root, path = thread(client, course)
    answer = ask(client, path).json()
    _branch, branch_path, _body = fork(client, path, answer)
    assert client.delete(branch_path).status_code == 204
    assert len(client.get(path + "/messages").json()) == 2
    _branch2, branch_path2, body2 = fork(client, path, answer)

    def deleting(question, history, context):
        assert client.delete(branch_path2).status_code == 409
        assert client.delete(path).status_code == 204
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", deleting)
    result = ask(client, branch_path2, body2["question"], body2["request_id"])
    assert result.status_code == 404
    with Session(db_engine) as db:
        assert checkpoint_counts(db) == [0, 0, 0, 0]
        assert db.scalars(select(Conversation)).all() == []
