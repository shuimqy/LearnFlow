from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest
from app.core.config import get_settings
from app.models import (
    Document,
    DocumentPage,
    ExtractionDraft,
    KnowledgeChunk,
    KnowledgePoint,
    KnowledgeRevision,
    PageExtraction,
    ProcessingTask,
)
from app.models.base import new_id
from app.schemas.extraction import ExtractedPage
from app.services import extraction, extraction_queue
from app.services.model_api import ModelAPIError
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from test_workspace import upload


def extracted_page():
    return ExtractedPage.model_validate(
        {
            "transcript": "A fraction and a worked example.",
            "warnings": [],
            "knowledge": [
                {
                    "title": "Fraction",
                    "summary": "A quotient",
                    "content": "The denominator is nonzero.",
                    "formulas": [
                        {
                            "latex": r"\frac{x^2}{y_1}",
                            "explanation": "y is nonzero.",
                            "uncertain": False,
                        }
                    ],
                    "warnings": [],
                }
            ],
            "examples": [
                {
                    "kind": "worked_example",
                    "title": "Example 1",
                    "question": r"Evaluate $\frac{4}{2}$.",
                    "answer": "2",
                    "solution": "",
                    "formulas": [{"latex": r"\frac{4}{2}", "explanation": "", "uncertain": False}],
                    "warnings": [],
                }
            ],
        }
    )


@pytest.fixture
def runner(db_engine, monkeypatch):
    monkeypatch.setattr(
        extraction, "SessionLocal", sessionmaker(bind=db_engine, expire_on_commit=False)
    )
    monkeypatch.setattr(extraction, "LLMClient", Mock())

    def infer(text, image, number, client):
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        return SimpleNamespace(
            parsed=extracted_page(), model="qwen3.8-flash", input_tokens=10, output_tokens=20
        )

    monkeypatch.setattr(extraction, "infer_page", infer)
    return infer


def queued(db_engine, document):
    run_id = new_id()
    with Session(db_engine) as db:
        task = db.get(ProcessingTask, document["task"]["id"])
        task.status, task.run_id = "queued", run_id
        db.commit()
    return document["task"]["id"], run_id


def payload(draft):
    return {
        key: draft[key]
        for key in ("title", "summary", "content", "formulas", "warnings", "example")
    }


def test_extraction_automatically_stores_formulas_examples_sources_and_revisions(
    client, course, pdf_bytes, db_engine, runner
):
    document = upload(client, course, pdf_bytes).json()
    extraction.process_document(*queued(db_engine, document))
    base = f"/api/documents/{document['id']}/extraction"
    overview = client.get(base).json()
    assert overview["task"]["status"] == "completed"
    assert overview["task"]["stage"] == "imported"
    page = client.get(base + "/pages/1").json()
    assert all(draft["status"] == "imported" for draft in page["drafts"])
    point = client.get(
        f"/api/courses/{course['id']}/knowledge/{page['drafts'][0]['knowledge_id']}"
    ).json()
    assert r"\frac{x^2}{y_1}" in point["content"]
    assert point["sources"][0]["page_number"] == 1
    assert point["sources"][0]["document_id"] == document["id"]
    assert "Chapter 1" in point["sources"][0]["quote"]
    example = client.get(
        f"/api/courses/{course['id']}/knowledge/{page['drafts'][1]['knowledge_id']}"
    ).json()
    assert "课件未提供解题步骤" in example["content"]
    assert "## 课件答案\n\n2" in example["content"]
    assert client.get(base + "/pages/2").json()["drafts"][0]["status"] == "duplicate"
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(KnowledgePoint.id))) == 2
        assert db.scalar(select(func.count(KnowledgeRevision.id))) == 2
        assert db.scalar(select(func.count(KnowledgeChunk.id))) >= 2
        assert all(value is None for value in db.scalars(select(KnowledgeChunk.embedding)))
        assert db.get(Document, document["id"]).status == "processed"
        reasons = db.scalars(select(KnowledgeRevision.reason)).all()
        assert all("自动提取课件" in reason and "核对" not in reason for reason in reasons)


def test_retry_only_failed_pages_and_preserves_user_edits(
    client, course, pdf_bytes, db_engine, runner, monkeypatch
):
    document = upload(client, course, pdf_bytes).json()

    def partial(text, image, number, model):
        if number == 2:
            raise ModelAPIError("private provider details")
        return runner(text, image, number, model)

    monkeypatch.setattr(extraction, "infer_page", partial)
    args = queued(db_engine, document)
    extraction.process_document(*args)
    base = f"/api/documents/{document['id']}/extraction"
    overview = client.get(base).json()
    assert overview["task"]["stage"] == "partial_failure"
    assert "private provider" not in str(overview)
    draft = client.get(base + "/pages/1").json()["drafts"][0]
    point_url = f"/api/courses/{course['id']}/knowledge/{draft['knowledge_id']}"
    edited = client.patch(
        point_url,
        json={
            "title": draft["title"],
            "summary": "",
            "content": "User corrected this definition.",
            "sources": [],
            "expected_version": 1,
            "reason": "Correct definition",
        },
    )
    assert edited.status_code == 200
    retries = []

    def retry(text, image, number, model):
        retries.append(number)
        return runner(text, image, number, model)

    monkeypatch.setattr(extraction, "infer_page", retry)
    extraction.process_document(*queued(db_engine, document))
    assert retries == [2]
    extraction.process_document(*args)
    assert client.get(base).json()["task"]["status"] == "completed"
    assert client.get(point_url).json()["content"] == "User corrected this definition."
    assert client.get(point_url).json()["version"] == 2


def test_existing_results_import_without_model_calls_and_skip_processed_entries(
    client, course, pdf_bytes, db_engine, runner, monkeypatch
):
    importer = extraction.import_page_results
    monkeypatch.setattr(extraction, "import_page_results", lambda *args: 0)
    document = upload(client, course, pdf_bytes).json()
    other = upload(client, course, pdf_bytes, "other.pdf").json()
    extraction.process_document(*queued(db_engine, document))
    extraction.process_document(*queued(db_engine, other))
    monkeypatch.setattr(extraction, "import_page_results", importer)
    base = f"/api/documents/{document['id']}/extraction"
    drafts = client.get(base + "/pages/1").json()["drafts"]
    accepted = client.post(base + f"/drafts/{drafts[0]['id']}/accept", json=payload(drafts[0]))
    assert accepted.status_code == 200
    point = accepted.json()
    assert (
        client.patch(
            f"/api/courses/{course['id']}/knowledge/{point['id']}",
            json={
                "title": point["title"],
                "summary": "",
                "content": "Already corrected",
                "sources": [],
                "expected_version": 1,
                "reason": "Manual correction",
            },
        ).status_code
        == 200
    )
    assert client.post(base + f"/drafts/{drafts[1]['id']}/discard").status_code == 204
    with Session(db_engine) as db:
        db.get(ProcessingTask, document["task"]["id"]).stage = "awaiting_review"
        db.commit()
    monkeypatch.setattr(
        extraction,
        "infer_page",
        lambda *args: pytest.fail("Existing results must not call the model"),
    )
    with Session(db_engine) as db:
        result = extraction.import_existing_document(db, document["id"])
        assert result["imported"] == 2
        assert extraction.import_existing_document(db, document["id"])["imported"] == 0
        assert db.get(KnowledgePoint, point["id"]).content == "Already corrected"
        assert db.get(KnowledgePoint, point["id"]).version == 2
    assert client.get(base + "/pages/1").json()["drafts"][1]["status"] == "discarded"
    other_page = client.get(f"/api/documents/{other['id']}/extraction/pages/1").json()
    assert all(draft["status"] == "pending" for draft in other_page["drafts"])


def test_import_failure_rolls_back_page_knowledge_revisions_and_chunks(
    client, course, pdf_bytes, db_engine, runner, monkeypatch
):
    document = upload(client, course, pdf_bytes).json()
    store = extraction.store_draft

    def fail_second(db, document, page, draft, *args, **kwargs):
        if draft.kind == "worked_example":
            raise RuntimeError("Synthetic write failure")
        return store(db, document, page, draft, *args, **kwargs)

    monkeypatch.setattr(extraction, "store_draft", fail_second)
    extraction.process_document(*queued(db_engine, document))
    with Session(db_engine) as db:
        for model in [KnowledgePoint, KnowledgeRevision, KnowledgeChunk, ExtractionDraft]:
            assert db.scalar(select(func.count(model.id))) == 0
        assert db.get(ProcessingTask, document["task"]["id"]).status == "failed"


def test_uncertain_formulas_and_page_warnings_are_kept_in_knowledge(
    client, course, pdf_bytes, db_engine, runner, monkeypatch
):
    def infer(text, image, number, model):
        response = runner(text, image, number, model)
        response.parsed.knowledge[0].formulas[0].uncertain = True
        response.parsed.warnings = ["The page is blurry."]
        return response

    monkeypatch.setattr(extraction, "infer_page", infer)
    document = upload(client, course, pdf_bytes).json()
    extraction.process_document(*queued(db_engine, document))
    points = client.get(f"/api/courses/{course['id']}/knowledge").json()
    point = next(point for point in points if point["title"] == "Fraction")
    assert "## 识别提示" in point["content"]
    assert "公式识别不确定" in point["content"]
    assert "The page is blurry." in point["content"]


def test_deleted_document_cannot_be_recreated_by_worker(
    client, course, pdf_bytes, db_engine, runner, monkeypatch
):
    document = upload(client, course, pdf_bytes).json()
    args = queued(db_engine, document)

    def deleting(text, image, number, model):
        assert client.delete(f"/api/documents/{document['id']}").status_code == 204
        return runner(text, image, number, model)

    monkeypatch.setattr(extraction, "infer_page", deleting)
    extraction.process_document(*args)
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(PageExtraction.id))) == 0
        assert db.scalar(select(func.count(ExtractionDraft.id))) == 0
        assert db.scalar(select(func.count(KnowledgePoint.id))) == 0


def test_queue_failure_keeps_upload_and_has_recoverable_status(
    client, course, pdf_bytes, monkeypatch
):
    monkeypatch.setattr(get_settings(), "extraction_auto_start", True)
    monkeypatch.setattr(get_settings(), "llm_api_key", SecretStr("sk-test-credential"))
    monkeypatch.setattr(
        get_settings(), "llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    monkeypatch.setattr(get_settings(), "llm_model", "qwen3.8-flash")
    connection = Mock()
    connection.ping.side_effect = RedisConnectionError("private URL")
    monkeypatch.setattr(extraction_queue, "redis_connection", lambda: connection)
    response = upload(client, course, pdf_bytes)
    assert response.status_code == 201
    document = response.json()
    assert document["task"]["stage"] == "queue_unavailable"
    assert "private URL" not in str(document)
    assert client.get(f"/api/documents/{document['id']}/file").content == pdf_bytes


def test_start_is_idempotent_while_queued(client, course, pdf_bytes, monkeypatch):
    document = upload(client, course, pdf_bytes).json()
    monkeypatch.setattr(get_settings(), "llm_api_key", SecretStr("sk-test-credential"))
    monkeypatch.setattr(
        get_settings(), "llm_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    monkeypatch.setattr(get_settings(), "llm_model", "qwen3.8-flash")
    monkeypatch.setattr(extraction_queue, "redis_connection", Mock())
    queue = Mock()
    monkeypatch.setattr(extraction_queue, "Queue", lambda *args, **kwargs: queue)
    from app.api import extraction as extraction_api

    monkeypatch.setattr(extraction_api, "reconcile_task", lambda *args: None)
    base = f"/api/documents/{document['id']}/extraction"
    assert client.post(base).json()["status"] == "queued"
    assert client.post(base).json()["status"] == "queued"
    assert queue.enqueue.call_count == 1


def test_extraction_and_images_are_owner_scoped(client, course, pdf_bytes, db_engine, runner):
    document = upload(client, course, pdf_bytes).json()
    extraction.process_document(*queued(db_engine, document))
    base = f"/api/documents/{document['id']}/extraction"
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={
            "email": "other-extraction@example.com",
            "name": "Other",
            "password": "another-password",
        },
    )
    for path in [base, base + "/pages/1", f"/api/documents/{document['id']}/pages/1/image"]:
        assert client.get(path).status_code == 404
    assert client.post(base).status_code == 404
    assert client.get(f"/api/courses/{course['id']}/knowledge").status_code == 404


def test_scanned_page_keeps_image_reference_without_fabricated_native_text(
    client, course, db_engine, runner
):
    with pymupdf.open() as source:
        source.new_page().insert_text((72, 72), "A scanned formula: x + y = 2")
        image = source[0].get_pixmap().tobytes("png")
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_image(page.rect, stream=image)
        data = pdf.tobytes()
    document = upload(client, course, data).json()
    extraction.process_document(*queued(db_engine, document))
    point = client.get(f"/api/courses/{course['id']}/knowledge").json()[0]
    assert point["sources"][0]["quote"] == ""
    assert point["sources"][0]["page_number"] == 1
    with Session(db_engine) as db:
        assert db.scalar(select(DocumentPage.text)) == ""


def test_missing_example_answer_is_preserved_as_missing(
    client, course, pdf_bytes, db_engine, runner, monkeypatch
):
    def infer(text, image, number, model):
        response = runner(text, image, number, model)
        example = response.parsed.examples[0]
        example.kind, example.answer, example.solution = "exercise", "", ""
        return response

    monkeypatch.setattr(extraction, "infer_page", infer)
    document = upload(client, course, pdf_bytes).json()
    extraction.process_document(*queued(db_engine, document))
    points = client.get(f"/api/courses/{course['id']}/knowledge").json()
    example = next(point for point in points if point["title"] == "Example 1")
    assert "课件未提供答案" in example["content"]
