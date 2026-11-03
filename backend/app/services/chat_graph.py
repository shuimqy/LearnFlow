import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.model_runtime import use_model_settings
from app.schemas.chat import AnswerDraft, ChatPlan, ConversationDraft, ImageObservation
from app.services.account_models import resolve_settings
from app.services.chat_context import current_evidence
from app.services.chat_generation import validate_answer
from app.services.chat_intent import asks_previous_question
from app.services.model_api import ModelAPIError
from app.services.retrieval import RetrievedContext, retrieve_course
from app.services.vector_index import enqueue_course_index

logger = logging.getLogger("learnflow.chat")


class ChatState(TypedDict):
    request_id: str
    question: str
    effective_question: str
    image_context: str
    has_images: bool
    history: list[dict]
    memory: dict
    previous_question: str | None
    intent: str
    query: str
    candidates: list[dict]
    items: list[dict]
    retrieved: bool
    retrieval_mode: str
    warnings: list[str]
    answer: dict | None
    model: str | None
    input_tokens: int
    output_tokens: int
    saved: bool


@dataclass
class ChatRuntime:
    db: object
    user_id: str
    course_id: str
    plan: Callable
    converse: Callable
    generate: Callable
    images: list[bytes]
    new_images: bool
    describe: Callable
    remember_images: Callable
    stage: Callable
    persist: Callable


def usage(state, response):
    return {
        "model": response.model,
        "input_tokens": state["input_tokens"] + response.input_tokens,
        "output_tokens": state["output_tokens"] + response.output_tokens,
    }


def observe_images(state: ChatState, runtime: Runtime[ChatRuntime]):
    ctx = runtime.context
    if not ctx.new_images or state["image_context"]:
        return {}
    ctx.stage("reading_images")
    settings = resolve_settings(ctx.db, ctx.user_id)
    ctx.db.commit()
    with use_model_settings(settings):
        response = ctx.describe(state["question"], ctx.images)
    observation = ImageObservation.model_validate(response.parsed)
    ctx.remember_images(observation.description)
    return {
        "image_context": observation.description,
        "warnings": list(dict.fromkeys([*state["warnings"], *observation.warnings])),
        **usage(state, response),
    }


def prepare_query(state: ChatState):
    previous = [row["content"] for row in state["history"] if row["role"] == "user"][-2:]
    effective = state["question"] or "请看看所附图片，题目清晰时帮助解答；缺少条件时先问清楚。"
    if state["image_context"]:
        effective += "\n\n用户附图的识别内容（可能有误，以原图为准）：\n" + state["image_context"]
    return {
        "query": "\n".join([*previous, effective])[-4000:],
        "effective_question": effective,
        "intent": "previous_question"
        if not state["image_context"] and asks_previous_question(state["question"])
        else "retrieve",
    }


def question_route(state: ChatState):
    return "recall" if state["intent"] == "previous_question" else "plan"


def recall(state: ChatState):
    previous = state["previous_question"]
    answer = AnswerDraft(
        status="conversation",
        answer=("你上一个问题是：\n\n> " + previous.replace("\n", "\n> "))
        if previous
        else "这段对话里，你还没有提出过其他问题。",
        supplement="",
        citations=[],
    )
    return {"answer": answer.model_dump(), "items": [], "retrieval_mode": "conversation"}


def plan(state: ChatState, runtime: Runtime[ChatRuntime]):
    ctx = runtime.context
    ctx.stage("planning")
    settings = resolve_settings(ctx.db, ctx.user_id)
    ctx.db.commit()
    try:
        with use_model_settings(settings):
            response = ctx.plan(
                state["effective_question"], state["history"], state["candidates"], state["memory"]
            )
        decision = ChatPlan.model_validate(response.parsed)
    except (ModelAPIError, ValidationError) as exc:
        logger.warning(
            "retrieval_planning_failed course=%s code=%s",
            ctx.course_id,
            exc.code if isinstance(exc, ModelAPIError) else "invalid_response",
        )
        if state["has_images"]:
            return {"intent": "image"}
        return {
            "intent": "retrieve",
            "warnings": [*state["warnings"], "暂未确定是否需要补查，本次检索课程知识。"],
        }
    route = decision.route
    if route == "context" and not state["candidates"]:
        route = "image" if state["has_images"] else "retrieve"
    if route == "image" and not state["has_images"]:
        route = "clarify"
    return {"intent": route, "query": decision.query or state["query"], **usage(state, response)}


def plan_route(state: ChatState):
    if state["intent"] in {"chat", "history", "clarify", "image"}:
        return "conversation"
    return "reuse" if state["intent"] == "context" else "retrieve"


def conversation(state: ChatState, runtime: Runtime[ChatRuntime]):
    ctx = runtime.context
    ctx.stage("generating")
    settings = resolve_settings(ctx.db, ctx.user_id)
    ctx.db.commit()
    with use_model_settings(settings):
        options = (
            {"images": ctx.images} if state["intent"] in {"image", "clarify"} and ctx.images else {}
        )
        response = ctx.converse(
            state["effective_question"],
            state["history"],
            state["intent"],
            state["memory"],
            **options,
        )
    result = ConversationDraft.model_validate(response.parsed)
    answer = AnswerDraft(
        status="needs_retrieval" if result.needs_retrieval else "conversation",
        answer=result.answer,
        supplement="",
        citations=[],
    )
    return {
        "answer": answer.model_dump(),
        "items": [],
        "query": result.query.strip() or state["query"],
        "retrieval_mode": "image"
        if state["intent"] == "image"
        else ("clarification" if state["intent"] == "clarify" else "conversation"),
        **usage(state, response),
    }


def reuse(state: ChatState, runtime: Runtime[ChatRuntime]):
    ctx = runtime.context
    ctx.stage("checking_context")
    items = current_evidence(ctx.db, ctx.course_id, ctx.user_id, state["candidates"])
    ctx.db.commit()
    # 部分引用过期时也重新查找，剩余片段不能悄悄替代完整的论证条件。
    if len(items) != len(state["candidates"]):
        return {
            "items": [],
            "warnings": [*state["warnings"], "先前的知识依据已变更，本次重新查找。"],
        }
    return {"items": items, "retrieval_mode": "context"}


def reuse_route(state: ChatState):
    return "generate" if state["items"] else "retrieve"


def retrieve(state: ChatState, runtime: Runtime[ChatRuntime]):
    ctx = runtime.context
    ctx.stage("retrieving")
    if get_settings().embedding_auto_index:
        enqueue_course_index(ctx.db, ctx.course_id)
    result = retrieve_course(ctx.db, ctx.course_id, ctx.user_id, state["query"])
    ctx.db.commit()
    return {
        "items": result.items,
        "retrieval_mode": result.mode,
        "retrieved": True,
        "warnings": list(dict.fromkeys([*state["warnings"], *result.warnings])),
    }


def evidence_route(state: ChatState):
    return "generate" if state["items"] else "insufficient"


def generate(state: ChatState, runtime: Runtime[ChatRuntime]):
    ctx = runtime.context
    ctx.stage("generating")
    settings = resolve_settings(ctx.db, ctx.user_id)
    ctx.db.commit()
    evidence = RetrievedContext(
        state["items"], state["retrieval_mode"], state["warnings"], images=ctx.images or None
    )
    with use_model_settings(settings):
        response = ctx.generate(state["effective_question"], state["history"], evidence)
    validate_answer(
        response.parsed,
        state["items"],
        allow_retrieval_request=state["retrieval_mode"] == "context",
    )
    return {"answer": response.parsed.model_dump(), **usage(state, response)}


def answer_route(state: ChatState):
    status = state["answer"]["status"]
    if status == "needs_retrieval" or (
        status == "insufficient" and state["retrieval_mode"] == "context"
    ):
        if state["retrieved"]:
            raise ModelAPIError(
                "An answer cannot request repeated retrieval.", code="invalid_response"
            )
        return "retrieve"
    return "validate"


def insufficient(state: ChatState):
    answer = AnswerDraft(
        status="insufficient",
        answer="当前课程知识库中没有找到足够相关的依据。可以补充相关课件、完善知识点，或把问题中的概念和条件写得更具体。",
        supplement="",
        citations=[],
    )
    return {"answer": answer.model_dump()}


def validate(state: ChatState, runtime: Runtime[ChatRuntime]):
    runtime.context.stage("validating")
    draft = AnswerDraft.model_validate(state["answer"])
    validate_answer(
        draft,
        state["items"],
        allow_conversation=state["retrieval_mode"] in {"conversation", "clarification", "image"},
    )
    return {"answer": draft.model_dump()}


def save(state: ChatState, runtime: Runtime[ChatRuntime]):
    runtime.context.stage("saving")
    runtime.context.persist(state)
    return {"saved": True}


def build_chat_graph(checkpointer=None):
    graph = StateGraph(ChatState, context_schema=ChatRuntime)
    for name, node in (
        ("observe_images", observe_images),
        ("prepare_query", prepare_query),
        ("recall", recall),
        ("plan", plan),
        ("conversation", conversation),
        ("reuse", reuse),
        ("retrieve", retrieve),
        ("generate", generate),
        ("insufficient", insufficient),
        ("validate", validate),
        ("save", save),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "observe_images")
    graph.add_edge("observe_images", "prepare_query")
    graph.add_conditional_edges(
        "prepare_query", question_route, {"recall": "recall", "plan": "plan"}
    )
    graph.add_edge("recall", "validate")
    graph.add_conditional_edges(
        "plan",
        plan_route,
        {"conversation": "conversation", "reuse": "reuse", "retrieve": "retrieve"},
    )
    graph.add_conditional_edges(
        "reuse", reuse_route, {"generate": "generate", "retrieve": "retrieve"}
    )
    graph.add_conditional_edges(
        "retrieve", evidence_route, {"generate": "generate", "insufficient": "insufficient"}
    )
    for name in ("conversation", "generate"):
        graph.add_conditional_edges(
            name, answer_route, {"retrieve": "retrieve", "validate": "validate"}
        )
    graph.add_edge("insufficient", "validate")
    graph.add_edge("validate", "save")
    graph.add_edge("save", END)
    return graph.compile(checkpointer=checkpointer)
