import json

import pytest
from app.core.config import get_settings
from app.models import Document
from app.schemas.chat import AnswerDraft, PdfPageAnswerDraft
from app.services import chat_generation
from app.services.chat_pdf import read_reference_pages
from app.services.llm import LLMResponse
from app.services.pdf_pages import render_page
from sqlalchemy.orm import Session
from test_chat import ask, thread
from test_knowledge import create, upload


def test_course_answer_requests_and_reads_the_selected_pdf_page(
    client, course, pdf_bytes, db_engine, monkeypatch
):
    monkeypatch.setattr(get_settings(), "llm_vision", True)
    document = upload(client, course, pdf_bytes)
    point = create(
        client,
        course,
        sources=[{"document_id": document["id"], "page_number": page} for page in (1, 2)],
    )
    with Session(db_engine) as db:
        stored = db.get(Document, document["id"])
        expected_image = render_page(stored, 2, max_side=1600)
        assert expected_image != render_page(stored, 1, max_side=1600)

    _, path = thread(client, course)
    responses = []

    class Model:
        def complete(self, messages, *, response_model, images, **kwargs):
            data = json.loads(messages[-1]["content"])
            responses.append(response_model)
            if response_model is PdfPageAnswerDraft:
                assert images is None
                sources = data["sources"][0]["sources"]
                assert [(source["page_ref"], source["page_number"]) for source in sources] == [
                    ("K1.1", 1),
                    ("K1.2", 2),
                ]
                parsed = response_model(
                    status="needs_pdf_pages",
                    answer="需要核对第二页的图。",
                    supplement="",
                    citations=[],
                    read_pdf_pages=["K1.2"],
                )
            else:
                assert images == [expected_image]
                assert data["pdf_page_images"] == [
                    {
                        "image_number": 1,
                        "citation": "K1",
                        "filename": document["filename"],
                        "page_number": 2,
                    }
                ]
                parsed = response_model(
                    status="answered",
                    answer="第二页的内容支持该结论 [K1]。",
                    supplement="",
                    citations=["K1"],
                )
            return LLMResponse("vision-test", "", parsed, 10, 5)

    monkeypatch.setattr(chat_generation, "LLMClient", Model)
    result = ask(client, path)
    assert result.status_code == 200, result.text
    answer = result.json()
    assert responses == [PdfPageAnswerDraft, AnswerDraft]
    assert answer["input_tokens"] == 20 and answer["output_tokens"] == 10
    assert answer["citations"][0]["knowledge_id"] == point["id"]
    assert answer["images"] == []


@pytest.mark.parametrize("vision", [True, False])
def test_unlisted_page_is_never_sent_to_the_model(client, course, pdf_bytes, monkeypatch, vision):
    monkeypatch.setattr(get_settings(), "llm_vision", vision)
    document = upload(client, course, pdf_bytes)
    create(client, course, sources=[{"document_id": document["id"], "page_number": 1}])
    _, path = thread(client, course)
    steps = []

    class Model:
        def complete(self, messages, *, response_model, images, **kwargs):
            data = json.loads(messages[-1]["content"])
            assert images is None
            steps.append(response_model)
            if response_model is PdfPageAnswerDraft:
                assert vision
                parsed = response_model(
                    status="needs_pdf_pages",
                    answer="需要核对另一页。",
                    supplement="",
                    citations=[],
                    read_pdf_pages=["K1.2"],
                )
            else:
                if vision:
                    assert data["pdf_page_images"] == []
                else:
                    assert "page_ref" not in data["sources"][0]["sources"][0]
                parsed = response_model(
                    status="insufficient", answer="找不到所需图示。", supplement="", citations=[]
                )
            return LLMResponse("vision-test", "", parsed, 10, 5)

    monkeypatch.setattr(chat_generation, "LLMClient", Model)
    result = ask(client, path)
    assert result.status_code == 200, result.text
    assert steps == ([PdfPageAnswerDraft, AnswerDraft] if vision else [AnswerDraft])
    assert any("引用页未能读取" in warning for warning in result.json()["warnings"]) == vision


def test_tool_does_not_open_a_document_outside_the_course(
    client, course, account, db_engine, pdf_bytes, monkeypatch
):
    other_course = client.post("/api/courses", json={"name": "另一门课"}).json()
    document = upload(client, other_course, pdf_bytes)

    def unexpected_render(*args, **kwargs):
        pytest.fail("The PDF tool must check document ownership before rendering")

    monkeypatch.setattr("app.services.chat_pdf.render_page", unexpected_render)
    items = [{"key": "K1", "sources": [{"document_id": document["id"], "page_number": 1}]}]
    with Session(db_engine) as db:
        assert read_reference_pages(db, course["id"], account["id"], items, ["K1.1"]) == []
