from app.api import account as account_api
from app.core.auth import DB, CurrentUser
from app.core.config import get_settings
from app.core.model_runtime import model_settings
from app.main import app
from app.schemas.account import ProbeResult
from app.schemas.chat import AnswerDraft, ChatPlan, ConversationDraft, ImageObservation
from app.schemas.proposal_review import ProposalReview
from app.services import chat, proposal_processing, workbook_assembly
from app.services.embeddings import EmbeddingBatch
from app.services.llm import LLMResponse
from app.services.model_api import ModelAPIError
from sqlalchemy.engine import make_url

if not (make_url(get_settings().database_url).database or "").endswith("_test"):
    raise RuntimeError("Browser fixtures require a dedicated test database")


def review_fixture(current, proposed, reason, sources, images, limited):
    review = ProposalReview(
        verdict="approve",
        basis="reasoning",
        opinion="测试审查：这条建议补充了必要条件，可以采纳。",
        reasons=["测试模型已检查建议的定义与条件。"],
        changes=["按建议更新正文。"],
        warnings=[],
        evidence=[],
        **{key: proposed[key] for key in ("title", "summary", "content")},
    )
    return LLMResponse("browser-test-model", review.model_dump_json(), review, 10, 20)


proposal_processing.review_proposal = review_fixture


def answer_fixture(question, history, context):
    key = context.items[0]["key"]
    answer = AnswerDraft(
        status="answered",
        answer=f"向量组线性无关，当且仅当零线性组合的系数全部为零：\n\n"
        "$$\n"
        r"\sum_{i=1}^{n} a_i v_i = 0 \implies a_1=\cdots=a_n=0"
        f"\n$$\n\n[{key}]",
        supplement="可通过齐次方程组只有零解来理解这个条件。",
        citations=[key],
    )
    if question == "长回答布局":
        answer.answer = "## 向量与线性组合\n\n" + "\n\n".join(
            f"**第 {number} 步**：检查向量组的零线性组合，保留变量的定义和成立条件。"
            f"只有全部系数为零时才得到零向量，才能据此判断线性无关。[{key}]"
            for number in range(1, 25)
        )
    return LLMResponse("browser-test-model", answer.model_dump_json(), answer, 10, 20)


chat.generate_answer = answer_fixture


def plan_fixture(question, history, evidence, memory):
    route = {
        "先缓一缓，今天有点学不动": "chat",
        "把我们刚才聊的内容总结一下": "history",
        "把刚才的判断条件说简单一点": "context",
        "这个怎么算": "clarify",
    }.get(question, "retrieve")
    if memory.get("has_images"):
        route = "image"
    return LLMResponse("browser-test-model", "", ChatPlan(route=route, query=""), 10, 5)


def conversation_fixture(question, history, route, memory, *, images=None):
    answers = {
        "chat": "可以先休息一下，等准备好了再继续。",
        "history": "我们刚才讨论了线性无关的判断条件。",
        "clarify": "你指的是哪道题？请补充题目或具体步骤。",
        "image": "图片中给出长 3、宽 2，矩形面积为 $3\\times 2=6$。",
    }
    if route == "image":
        if not images:
            raise ModelAPIError("The image fixture requires image bytes")
        if "模拟图片回答失败" in question:
            raise ModelAPIError("Private browser fixture failure")
    result = ConversationDraft(answer=answers[route], needs_retrieval=False, query="")
    return LLMResponse("browser-test-model", "", result, 10, 10)


chat.plan_question = plan_fixture
chat.generate_conversation = conversation_fixture


def describe_fixture(question, images):
    if not images or not all(data.startswith((b"\x89PNG", b"\xff\xd8")) for data in images):
        raise ModelAPIError("Invalid image fixture input")
    result = ImageObservation(description="固定测试：图片中给出矩形，长 3、宽 2。", warnings=[])
    return LLMResponse("browser-test-model", "", result, 10, 10)


chat.describe_images = describe_fixture


class AccountLLMFixture:
    def complete(self, *args, **kwargs):
        settings = model_settings()
        if settings.llm_model == "unavailable-model":
            raise ModelAPIError("Model unavailable in browser fixture")
        result = ProbeResult(status="ok", answer="LearnFlow OK")
        return LLMResponse(settings.llm_model, result.model_dump_json(), result, 10, 10)


class AccountEmbeddingFixture:
    def embed(self, texts):
        settings = model_settings()
        vector = [1.0] + [0.0] * (settings.embedding_dimensions - 1)
        return EmbeddingBatch(
            [vector for _ in texts], settings.embedding_model, settings.embedding_dimensions, 10
        )


account_api.LLMClient = AccountLLMFixture
account_api.EmbeddingClient = AccountEmbeddingFixture

__all__ = ["app"]


@app.post("/__test/documents/{document_id}/workbook-exercises")
def seed_workbook_exercises(document_id: str, user: CurrentUser, db: DB, organized: bool = False):
    from app.api.dependencies import owned_document
    from app.models import (
        Chapter,
        DocumentStructure,
        ExerciseLayout,
        ExtractionDraft,
        PageExtraction,
    )
    from app.schemas.knowledge import KnowledgeInput
    from app.services.knowledge import create_knowledge

    document = owned_document(db, document_id, user.id)
    pages = {}
    for number in range(1, min(2, document.page_count) + 1):
        page = PageExtraction(
            document_id=document.id,
            page_number=number,
            status="completed",
            transcript="Synthetic workbook fixture",
            warnings=[],
        )
        db.add(page)
        db.flush()
        pages[number] = page.id
    for index, (title, question, answer, solution) in enumerate(
        [
            ("分式计算", r"计算 $\frac{4}{2}$。", "2", "分子除以分母。"),
            ("线性方程", r"求解 $2x + 1 = 5$。", "$x=2$", "等式两边先减一，再除以二。"),
            ("无答案习题", r"讨论向量组 $v_1,v_2$ 的线性无关条件。", "", ""),
        ]
    ):
        point = create_knowledge(
            db, document.course_id, user.id, KnowledgeInput(title=title, content=question)
        )
        draft = ExtractionDraft(
            extraction_id=pages[1 if index < 2 else max(pages)],
            position=index,
            kind="exercise",
            title=title,
            summary="",
            content=question,
            formulas=[],
            warnings=[],
            status="imported",
            knowledge_id=point.id,
            example={
                "question": question,
                "answer": answer,
                "solution": solution,
                "warnings": [],
            },
        )
        db.add(draft)
        db.flush()
        if organized:
            db.add(
                ExerciseLayout(
                    draft_id=draft.id,
                    question_type="calculation" if index < 2 else "proof",
                    difficulty="basic" if index == 0 else "intermediate",
                    knowledge_tags=["代数运算" if index < 2 else "线性无关"],
                    regions=[],
                    status="pending",
                    warnings=[],
                )
            )
    if organized:
        db.add(
            DocumentStructure(
                document_id=document.id, version=1, status="completed", progress=100, warnings=[]
            )
        )
        db.add(
            Chapter(
                document_id=document.id,
                title="第一章 基本运算",
                start_page=1,
                end_page=1,
                position=0,
                source="outline",
            )
        )
        if document.page_count > 1:
            db.add(
                Chapter(
                    document_id=document.id,
                    title="第二章 向量",
                    start_page=2,
                    end_page=document.page_count,
                    position=1,
                    source="outline",
                )
            )
    db.commit()
    return {"created": 3}


@app.get("/__test/workbook-source.pdf")
def workbook_source(user: CurrentUser):
    import pymupdf
    from fastapi import Response

    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 45), "Chapter 1: Calculations", fontsize=18)
        page.insert_text((50, 95), "Q1. Calculate the fraction:", fontsize=14)
        page.insert_text((95, 125), "4", fontsize=16)
        page.draw_line((88, 132), (115, 132))
        page.insert_text((95, 154), "2", fontsize=16)
        page.draw_rect((170, 110, 265, 160), color=(0, 0.3, 0.1))
        page.insert_text((50, 330), "Q2. Solve 2x + 1 = 5.", fontsize=14)
        page.insert_text((50, 740), "ANSWER AREA: 2", fontsize=12)
        page = pdf.new_page()
        page.insert_text((50, 45), "Chapter 2: Vectors", fontsize=18)
        page.insert_text((50, 100), "Discuss linear independence.", fontsize=14)
        pdf.set_toc([[1, "Chapter 1: Calculations", 1], [1, "Chapter 2: Vectors", 2]])
        return Response(pdf.tobytes(), media_type="application/pdf")


class AssemblyFixture:
    def complete(self, messages, *, response_model, **kwargs):
        import json

        from app.schemas.workbook_assembly import AssemblyPlan, SelectionOrder

        body = json.loads(messages[-1]["content"])
        if response_model is AssemblyPlan:
            result = AssemblyPlan(
                title="第一章原题练习",
                count=2,
                chapter_ids=[body["chapters"][0]["id"]],
                type_counts=[],
                difficulty_counts=[],
                topics=["代数运算"],
                warnings=[],
            )
        else:
            result = SelectionOrder(
                draft_ids=[item["draft_id"] for item in body["candidates"]],
                explanation="覆盖已有计算题。",
            )
        return LLMResponse("browser-fixture", "", result, 10, 10)


workbook_assembly.LLMClient = AssemblyFixture
