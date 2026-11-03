from types import SimpleNamespace

import pytest
from app.models import ExtractionDraft
from app.schemas.workbook_assembly import AssemblyPlan, SelectionOrder
from app.services import workbook_assembly
from app.services.llm import LLMResponse
from app.services.workbook_assembly import all_questions_request, unique_candidates
from sqlalchemy.orm import Session
from test_workbooks import exercises as exercises  # noqa: PLC0414
from test_workbooks import save


@pytest.mark.parametrize(
    "text",
    [
        "所有题都要，但是把重复题去掉",
        "全部题目，去重",
        "请帮我收集所有原题并去除重复题",
        "全部原题",
    ],
)
def test_all_questions_requests_have_a_local_route(text):
    assert all_questions_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "不要所有题",
        "除了所有题中的计算题",
        "第一章所有题",
        "所有题里选5道",
        "所有题都不要",
        "全部题目但保留重复题",
    ],
)
def test_scoped_or_negative_requests_are_not_misread_as_plain_all(text):
    assert not all_questions_request(text)


def test_dedup_preserves_operators_case_and_decimal_points():
    rows = [
        {"draft_id": str(index), "question": question}
        for index, question in enumerate(
            [
                "1. 计算 $x+y$。",
                "2. 计算 $x+y$。",
                "计算 $x-y$。",
                "计算 $A$。",
                "计算 $a$。",
                "计算 $1.5$。",
                "计算 $15$。",
            ]
        )
    ]
    assert len(unique_candidates(rows)) == 6


def test_all_questions_is_local_uncapped_at_ten_and_reports_duplicates(
    client, course, exercises, db_engine, monkeypatch
):
    def unexpected():
        pytest.fail("All-question deduplication must not call the LLM")

    monkeypatch.setattr(workbook_assembly, "LLMClient", unexpected)
    with Session(db_engine) as db:
        source = db.get(ExtractionDraft, exercises["items"][0]["draft_id"])
        for i in range(1, 15):
            example = {**source.example, "question": f"计算 ${i} + 1$。"}
            db.add(
                ExtractionDraft(
                    extraction_id=source.extraction_id,
                    position=i,
                    kind="exercise",
                    title=f"计算 {i}",
                    summary="",
                    content=example["question"],
                    formulas=[],
                    warnings=[],
                    example=example,
                    status="imported",
                    knowledge_id=source.knowledge_id,
                )
            )
        db.add(
            ExtractionDraft(
                extraction_id=source.extraction_id,
                position=20,
                kind="exercise",
                title="重复题",
                summary="",
                content=source.content,
                formulas=[],
                warnings=[],
                example=source.example,
                status="imported",
                knowledge_id=source.knowledge_id,
            )
        )
        db.commit()
    path = f"/api/courses/{course['id']}/workbooks/assemble"
    response = client.post(path, json={"instructions": "所有题都要，但是把重复题去掉"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["report"]["selected"] == 16
    assert result["report"]["duplicates_removed"] == 1
    assert result["report"]["selection_mode"] == "all" and result["report"]["method"] == "rules"
    assert sum(len(group["items"]) for group in result["sections"]) == 16
    assert client.post(path, json={"selection_mode": "all"}).json()["report"]["selected"] == 16
    assert (
        client.post(path, json={"instructions": "所有题都要", "count": 5}).json()["report"][
            "selected"
        ]
        == 5
    )


def test_empty_model_title_is_filled_by_server(client, course, exercises, monkeypatch):
    def complete(messages, *, response_model, **kwargs):
        if response_model is AssemblyPlan:
            parsed = AssemblyPlan(
                title="",
                count=1,
                chapter_ids=[],
                type_counts=[],
                difficulty_counts=[],
                topics=[],
                warnings=[],
            )
        else:
            parsed = SelectionOrder(
                draft_ids=[exercises["items"][0]["draft_id"]], explanation="按要求选题。"
            )
        return LLMResponse("fixture", "", parsed, 1, 1)

    monkeypatch.setattr(workbook_assembly, "LLMClient", lambda: SimpleNamespace(complete=complete))
    response = client.post(
        f"/api/courses/{course['id']}/workbooks/assemble",
        json={"instructions": "按主要知识点选一道"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == course["name"] + " · 原题练习"


def test_rename_only_changes_name_and_checks_version_and_owner(client, course, exercises):
    book = save(client, exercises)
    path = exercises["base"] + f"/{book['id']}/title"
    response = client.patch(path, json={"expected_version": 1, "title": "  计算题册  "})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["title"] == "计算题册" and result["version"] == 2
    assert result["sections"] == book["sections"] and result["settings"] == book["settings"]
    assert client.patch(path, json={"expected_version": 1, "title": "旧标签页"}).status_code == 409
    assert client.patch(path, json={"expected_version": 2, "title": " "}).status_code == 422
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={
            "name": "其他用户",
            "email": "rename-other@example.com",
            "password": "test-password-2026",
        },
    )
    assert client.patch(path, json={"expected_version": 2, "title": "不应修改"}).status_code == 404
