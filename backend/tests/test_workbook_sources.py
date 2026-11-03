import copy

import pytest
from app.models import ExtractionDraft, PageExtraction
from app.services import workbook_assembly
from sqlalchemy.orm import Session
from test_document_organization import structured as structured  # noqa: PLC0414
from test_knowledge import upload
from test_workbooks import exercises as exercises  # noqa: PLC0414


@pytest.fixture
def second_source(client, course, pdf_bytes, exercises, db_engine):
    document = upload(client, course, pdf_bytes)
    with Session(db_engine) as db:
        page = PageExtraction(
            document_id=document["id"],
            page_number=2,
            status="completed",
            transcript="synthetic",
            warnings=[],
        )
        db.add(page)
        db.flush()
        draft = db.get(ExtractionDraft, exercises["items"][0]["draft_id"])
        example = copy.deepcopy(draft.example)
        example["question"] = "求矩阵 $B$ 的秩。"
        db.add(
            ExtractionDraft(
                extraction_id=page.id,
                position=0,
                kind="exercise",
                title="矩阵秩",
                summary="",
                content=example["question"],
                formulas=[],
                warnings=[],
                status="imported",
                knowledge_id=draft.knowledge_id,
                example=example,
            )
        )
        db.commit()
    return document


def test_manual_and_automatic_selection_share_document_chapter_and_page_scope(
    client, course, structured, second_source
):
    first = structured["document"]["id"]
    second = second_source["id"]
    base = f"/api/courses/{course['id']}"
    for ids, expected in [([first], 2), ([second], 1), ([first, second], 3)]:
        listed = client.get(base + "/exercises", params={"document_ids": ids}).json()
        assembled = client.post(
            base + "/workbooks/assemble", json={"document_ids": ids, "selection_mode": "all"}
        ).json()
        assert listed["total"] == assembled["report"]["selected"] == expected
        assert {item["draft_id"] for item in listed["items"]} == {
            item["draft_id"] for group in assembled["sections"] for item in group["items"]
        }
    both = {"document_ids": [first, second], "page_from": 2, "page_to": 2}
    assert client.get(base + "/exercises", params=both).json()["total"] == 2
    assert (
        client.post(base + "/workbooks/assemble", json={**both, "selection_mode": "all"}).json()[
            "report"
        ]["selected"]
        == 2
    )
    scope = {
        "document_ids": [first],
        "chapter_ids": [structured["chapters"][0]["id"]],
        "page_from": 2,
    }
    assert client.get(base + "/exercises", params=scope).json()["total"] == 0
    assert (
        client.post(base + "/workbooks/assemble", json={**scope, "selection_mode": "all"}).json()[
            "report"
        ]["selected"]
        == 0
    )


def test_invalid_scope_is_rejected_before_model_call(
    client, course, structured, second_source, monkeypatch
):
    def unexpected():
        pytest.fail("Invalid scope must be rejected before using the model")

    monkeypatch.setattr(workbook_assembly, "LLMClient", unexpected)
    base = f"/api/courses/{course['id']}"
    path = base + "/workbooks/assemble"
    for scope, status in [
        ({"document_ids": []}, 422),
        ({"document_ids": ["missing"]}, 404),
        ({"page_from": 2, "page_to": 1}, 422),
        (
            {
                "document_ids": [second_source["id"]],
                "chapter_ids": [structured["chapters"][0]["id"]],
            },
            422,
        ),
    ]:
        response = client.post(path, json={**scope, "instructions": "根据知识点选题"})
        assert response.status_code == status, response.text
    other = client.post("/api/courses", json={"name": "另一门课程"}).json()
    first = structured["document"]["id"]
    assert (
        client.get(
            f"/api/courses/{other['id']}/exercises", params={"document_ids": [first]}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/courses/{other['id']}/workbooks/assemble",
            json={"document_ids": [first], "instructions": "选题"},
        ).status_code
        == 404
    )
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={
            "name": "其他用户",
            "email": "sources-other@example.com",
            "password": "test-password-2026",
        },
    )
    own = client.post("/api/courses", json={"name": "我的课程"}).json()
    assert (
        client.post(
            f"/api/courses/{own['id']}/workbooks/assemble",
            json={"document_ids": [first], "instructions": "选题"},
        ).status_code
        == 404
    )
