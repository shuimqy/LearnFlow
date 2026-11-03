import json
from uuid import uuid4

import httpx
import pytest
from app.core.config import get_settings
from app.core.model_runtime import model_settings
from app.schemas.chat import AnswerDraft, ChatPlan, ConversationDraft
from app.services import chat, chat_intent
from app.services.chat_context import current_evidence
from app.services.llm import LLMClient, LLMResponse
from app.services.model_api import ModelAPIError
from sqlalchemy.orm import Session
from test_chat import answer_fixture, ask, thread
from test_chat_branches import fork
from test_knowledge import create, payload


def response(parsed, input_tokens=10, output_tokens=5):
    return LLMResponse("test-model", parsed.model_dump_json(), parsed, input_tokens, output_tokens)


def set_plan(monkeypatch, route, query="", callback=None):
    def plan(question, history, candidates, memory):
        if callback:
            callback(question, history, candidates, memory)
        return response(ChatPlan(route=route, query=query))

    monkeypatch.setattr(chat, "plan_question", plan)


def no_retrieval(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("This route must not retrieve or enqueue embeddings")

    monkeypatch.setattr("app.services.chat_graph.retrieve_course", blocked)
    monkeypatch.setattr("app.services.chat_graph.enqueue_course_index", blocked)


@pytest.mark.parametrize(
    "route,question",
    [
        ("chat", "这节课学得有点累，陪我聊一下"),
        ("history", "把我们前面的讨论整理成三句话"),
        ("clarify", "这个怎么算"),
    ],
)
def test_conversation_routes_do_not_embed_or_retrieve(client, course, monkeypatch, route, question):
    set_plan(monkeypatch, route)
    no_retrieval(monkeypatch)

    def converse(question, history, actual_route, memory):
        assert actual_route == route
        assert model_settings().llm_model == get_settings().llm_model
        return response(
            ConversationDraft(answer="先说说你现在的想法。", needs_retrieval=False, query="")
        )

    monkeypatch.setattr(chat, "generate_conversation", converse)
    _root, path = thread(client, course)
    result = ask(client, path, question)
    assert result.status_code == 200, result.text
    answer = result.json()
    assert answer["retrieval_mode"] == ("clarification" if route == "clarify" else "conversation")
    assert not answer["citations"] and not answer["warnings"]
    assert answer["input_tokens"] == 20 and answer["output_tokens"] == 10
    assert client.get(path + "/messages").json()[-1]["id"] == answer["id"]


def seed_answer(client, course, monkeypatch):
    point = create(client, course)
    root, path = thread(client, course)
    monkeypatch.setattr(chat, "generate_answer", answer_fixture)
    answer = ask(client, path).json()
    assert answer["citations"]
    return point, root, path, answer


def test_context_followup_reuses_current_evidence_and_keeps_citations(client, course, monkeypatch):
    point, _root, path, _answer = seed_answer(client, course, monkeypatch)
    set_plan(monkeypatch, "context", "线性无关定义中的系数条件")
    no_retrieval(monkeypatch)

    def generate(question, history, context):
        assert context.mode == "context" and context.items[0]["knowledge_id"] == point["id"]
        assert "补充解释来自当前条件的推导" in history[-1]["content"]
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", generate)
    result = ask(client, path, "能把刚才那个条件说简单一点吗")
    assert result.status_code == 200, result.text
    assert result.json()["retrieval_mode"] == "context"
    assert result.json()["citations"][0]["current"]
    assert not result.json()["warnings"]


def test_rewritten_query_is_used_for_retrieval(client, course, monkeypatch):
    create(client, course)
    _root, path = thread(client, course)
    set_plan(monkeypatch, "retrieve", "线性无关的定义和系数条件")
    captured = []
    from app.services.retrieval import retrieve_course

    def retrieve(db, course_id, user_id, query):
        captured.append(query)
        return retrieve_course(db, course_id, user_id, query)

    monkeypatch.setattr("app.services.chat_graph.retrieve_course", retrieve)
    monkeypatch.setattr(chat, "generate_answer", answer_fixture)
    assert ask(client, path, "它是怎么判断的？").status_code == 200
    assert captured == ["线性无关的定义和系数条件"]


@pytest.mark.parametrize("initial_route", ["context", "context_insufficient", "chat"])
def test_generation_can_request_one_retrieval_without_saving_intermediate_answer(
    client, course, monkeypatch, initial_route
):
    _point, _root, path, _answer = seed_answer(client, course, monkeypatch)
    set_plan(
        monkeypatch,
        "context" if initial_route.startswith("context") else "chat",
        "线性无关的补充条件",
    )
    calls = []

    def converse(*args):
        return response(
            ConversationDraft(
                answer="需要补查，不能直接展示。", needs_retrieval=True, query="线性无关的补充条件"
            )
        )

    def generate(question, history, context):
        calls.append(context.mode)
        if context.mode == "context":
            return response(
                AnswerDraft(
                    status="insufficient"
                    if initial_route == "context_insufficient"
                    else "needs_retrieval",
                    answer="需要补查，不能直接展示。",
                    supplement="",
                    citations=[],
                )
            )
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_conversation", converse)
    monkeypatch.setattr(chat, "generate_answer", generate)
    result = ask(client, path, "继续解释，必要时查找依据")
    assert result.status_code == 200, result.text
    assert "不能直接展示" not in result.json()["content"]
    assert result.json()["retrieval_mode"] == "text"
    assert calls == (["context", "text"] if initial_route.startswith("context") else ["text"])
    assert len(client.get(path + "/messages").json()) == 4
    assert result.json()["input_tokens"] == 120


def test_planner_failure_safely_falls_back_to_retrieval(client, course, monkeypatch, caplog):
    create(client, course)
    _root, path = thread(client, course)

    def fail(*args):
        raise ModelAPIError("private planner response sk-secret", code="invalid_response")

    monkeypatch.setattr(chat, "plan_question", fail)
    monkeypatch.setattr(chat, "generate_answer", answer_fixture)
    result = ask(client, path)
    assert result.status_code == 200 and result.json()["citations"]
    assert "补查" in "".join(result.json()["warnings"])
    assert "private" not in result.text and "sk-secret" not in caplog.text


@pytest.mark.parametrize("when", ["before", "planning"])
def test_stale_context_forces_new_retrieval(client, course, monkeypatch, when):
    point, _root, path, _answer = seed_answer(client, course, monkeypatch)

    def update():
        result = client.patch(
            f"/api/courses/{course['id']}/knowledge/{point['id']}",
            json=payload(
                content="线性无关的最新条件：零线性组合只能有全零系数。",
                expected_version=1,
                reason="修订",
            ),
        )
        assert result.status_code == 200

    if when == "before":
        update()
    set_plan(
        monkeypatch,
        "context",
        "线性无关的最新条件",
        callback=(lambda *args: update()) if when == "planning" else None,
    )
    calls = []

    def generate(question, history, context):
        calls.append(context.mode)
        assert context.items[0]["version"] == 2
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", generate)
    result = ask(client, path, "请接着解释那个条件")
    assert result.status_code == 200, result.text
    assert calls == ["text"] and result.json()["citations"][0]["version"] == 2


def test_context_edit_during_generation_is_rejected(client, course, monkeypatch):
    point, _root, path, _answer = seed_answer(client, course, monkeypatch)
    set_plan(monkeypatch, "context", "线性无关定义")
    no_retrieval(monkeypatch)

    def edit(question, history, context):
        assert (
            client.patch(
                f"/api/courses/{course['id']}/knowledge/{point['id']}",
                json=payload(expected_version=1, content="线性无关更新后的定义", reason="并发修订"),
            ).status_code
            == 200
        )
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", edit)
    result = ask(client, path, "换个说法解释一下")
    assert result.status_code == 409
    assert client.get(path + "/messages").json()[-1]["status"] == "failed"


def test_branch_uses_fork_evidence_and_never_later_main_messages(client, course, monkeypatch):
    point, _root, path, answer = seed_answer(client, course, monkeypatch)
    _branch, branch_path, body = fork(client, path, answer, question="能把这段定义讲直白一点吗")
    other = create(client, course, title="另外的知识", content="later-main-only")
    assert ask(client, path, "later-main-only").status_code == 200

    def check(question, history, candidates, memory):
        assert candidates and {item["knowledge_id"] for item in candidates} == {point["id"]}
        assert "later-main-only" not in json.dumps(history, ensure_ascii=False)

    set_plan(monkeypatch, "context", "线性无关定义", check)
    no_retrieval(monkeypatch)
    result = ask(client, branch_path, body["question"], body["request_id"])
    assert result.status_code == 200 and result.json()["retrieval_mode"] == "context"
    assert result.json()["citations"][0]["knowledge_id"] != other["id"]
    assert len(client.get(path + "/messages").json()) == 4


def test_evidence_cannot_cross_course_or_user_boundaries(
    client, course, account, db_engine, monkeypatch
):
    _point, _root, _path, answer = seed_answer(client, course, monkeypatch)
    other = client.post("/api/courses", json={"name": "另一门课"}).json()
    with Session(db_engine) as db:
        assert current_evidence(db, other["id"], account["id"], answer["citations"]) == []
        assert current_evidence(db, course["id"], str(uuid4()), answer["citations"]) == []


def test_general_recall_receives_first_question_and_excludes_future_messages(
    client, course, monkeypatch
):
    _root, path = thread(client, course)
    ask(client, path, "最早的测试提问")
    set_plan(monkeypatch, "history")

    def converse(question, history, route, memory):
        assert memory["first_question"] == "最早的测试提问"
        return response(
            ConversationDraft(
                answer="你最早问的是：最早的测试提问。", needs_retrieval=False, query=""
            )
        )

    monkeypatch.setattr(chat, "generate_conversation", converse)
    no_retrieval(monkeypatch)
    assert ask(client, path, "我在这个聊天里最开始问的啥？").status_code == 200


def test_planner_uses_structured_model_and_does_not_receive_credentials(monkeypatch):
    from test_llm import reply, settings

    def provider(request):
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["name"] == "ChatPlan"
        data = json.loads(body["messages"][-1]["content"])
        assert set(data) == {"question", "history", "memory", "current_evidence"}
        assert "sk-" not in body["messages"][-1]["content"]
        return httpx.Response(200, json=reply('{"route":"history","query":""}'))

    monkeypatch.setattr(
        chat_intent,
        "LLMClient",
        lambda: LLMClient(settings(), transport=httpx.MockTransport(provider)),
    )
    result = chat_intent.plan_question("我们刚才都讨论了什么？", [], [], {})
    assert result.parsed.route == "history"
