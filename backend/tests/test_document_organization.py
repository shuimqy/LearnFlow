from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.models import Chapter, DocumentStructure, KnowledgeSource
from app.models.base import new_id
from app.schemas.document_structure import PageLayouts
from app.schemas.workbook_assembly import AssemblyPlan, SelectionOrder
from app.services import document_organization as organization
from app.services import workbook_assembly
from app.services.chapters import detect_chapters
from app.services.llm import LLMResponse
from app.services.workbook_assembly import select_candidates
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_workbooks import exercises as exercises  # noqa: PLC0414


@pytest.fixture
def structured(client, course, exercises, db_engine):
    with Session(db_engine) as db:
        for index, point in enumerate(exercises["points"], 1):
            db.add(
                KnowledgeSource(
                    knowledge_id=point["id"],
                    document_id=exercises["document"]["id"],
                    filename="lecture.pdf",
                    page_number=index,
                    quote="synthetic",
                    position=0,
                )
            )
        db.commit()
    response = client.put(
        f"/api/documents/{exercises['document']['id']}/chapters",
        json={
            "expected_version": 0,
            "chapters": [
                {"title": "第一章 分式", "start_page": 1, "end_page": 1},
                {"title": "第二章 运算", "start_page": 2, "end_page": 2},
            ],
        },
    )
    assert response.status_code == 200, response.text
    return {
        **exercises,
        "chapters": response.json()["chapters"],
        "course": course,
        "structure": f"/api/documents/{exercises['document']['id']}/structure",
    }


def test_chapters_associate_knowledge_exercises_and_manual_ranges(client, structured):
    course_id = structured["course"]["id"]
    chapter = structured["chapters"][0]
    assert chapter["knowledge_count"] == chapter["exercise_count"] == 1
    assert (
        len(client.get(f"/api/courses/{course_id}/knowledge?chapter_id={chapter['id']}").json())
        == 1
    )
    assert (
        client.get(f"/api/courses/{course_id}/exercises?chapter_id={chapter['id']}").json()[
            "items"
        ][0]["chapter"]["id"]
        == chapter["id"]
    )
    path = f"/api/documents/{structured['document']['id']}/chapters"
    update = {"expected_version": 1, "chapters": [{**chapter, "end_page": 2}]}
    response = client.put(path, json=update)
    assert response.status_code == 200 and response.json()["version"] == 2
    assert response.json()["chapters"][0]["exercise_count"] == 2
    assert client.put(path, json=update).status_code == 409
    assert (
        client.get(
            f"/api/courses/{course_id}/exercises?chapter_id={structured['chapters'][1]['id']}"
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "chapters",
    [
        [
            {"title": "重复范围", "start_page": 1, "end_page": 2},
            {"title": "重叠", "start_page": 2, "end_page": 2},
        ],
        [{"title": "越界", "start_page": 1, "end_page": 3}],
        [{"title": "倒序", "start_page": 2, "end_page": 1}],
        [{"title": " ", "start_page": 1, "end_page": 1}],
        [{"id": "foreign", "title": "伪造", "start_page": 1, "end_page": 1}],
    ],
)
def test_invalid_chapters_are_atomic(client, structured, chapters):
    path = f"/api/documents/{structured['document']['id']}/chapters"
    assert client.put(path, json={"expected_version": 1, "chapters": chapters}).status_code == 422
    state = client.get(structured["structure"]).json()
    assert state["version"] == 1 and len(state["chapters"]) == 2


def test_native_outline_and_headings_need_no_model():
    ranges, source, _warnings = detect_chapters(
        [(1, "向量", 2), (2, "小节", 3), (1, "矩阵", 4)], [], 5, allow_model=False
    )
    assert (
        ranges == [("导读与前置资料", 1, 1), ("向量", 2, 3), ("矩阵", 4, 5)] and source == "outline"
    )
    ranges, source, _ = detect_chapters(
        [],
        [
            {"page": 1, "text": "第1章 向量"},
            {"page": 2, "text": "第1章 向量"},
            {"page": 3, "text": "第二章 矩阵"},
        ],
        3,
        allow_model=False,
    )
    assert len(ranges) == 2 and source == "heading"
    assert (
        detect_chapters([], [{"page": 1, "text": "无明确边界"}], 1, allow_model=False)[1]
        == "fallback"
    )


def test_organization_queue_failure_is_explicit(client, structured, monkeypatch):
    monkeypatch.setattr(
        organization,
        "redis_connection",
        lambda: SimpleNamespace(ping=lambda: (_ for _ in ()).throw(RedisConnectionError())),
    )
    result = client.post(structured["structure"], json={"expected_version": 1})
    assert result.status_code == 202 and result.json()["status"] == "failed"
    assert "队列" in result.json()["error"]


def prepare_worker(db_engine, structured, monkeypatch, settings=None):
    monkeypatch.setattr(
        organization, "SessionLocal", sessionmaker(bind=db_engine, expire_on_commit=False)
    )
    monkeypatch.setattr(
        organization, "resolve_settings", lambda *a: settings or Settings(_env_file=None)
    )
    monkeypatch.setattr(
        organization, "document_digest", lambda *a: ([(1, "章一", 1), (1, "章二", 2)], [])
    )
    run_id = new_id()
    with Session(db_engine) as db:
        state = db.get(DocumentStructure, structured["document"]["id"])
        state.status, state.run_id = "queued", run_id
        db.commit()
    return run_id


def test_background_organization_uses_native_outline_and_real_state(
    client, structured, db_engine, monkeypatch
):
    run = prepare_worker(db_engine, structured, monkeypatch)
    organization.organize_document(structured["document"]["id"], run)
    result = client.get(structured["structure"]).json()
    assert result["status"] == "completed" and result["progress"] == 100
    assert [row["title"] for row in result["chapters"]] == ["章一", "章二"]
    assert result["warnings"] and result["version"] == 2


def test_background_regions_are_suggestions_and_do_not_overwrite_confirmed(
    client, structured, db_engine, monkeypatch
):
    settings = Settings(
        _env_file=None,
        llm_model="fixture",
        llm_api_key=SecretStr("fixed-test-key"),
        llm_base_url="https://models.example.com",
    )
    run = prepare_worker(db_engine, structured, monkeypatch, settings)

    def infer(number, items, image):
        assert image.startswith(b"\x89PNG")
        return PageLayouts.model_validate(
            {
                "exercises": [
                    {
                        "draft_id": item["draft_id"],
                        "question_type": "calculation",
                        "difficulty": "basic",
                        "knowledge_tags": ["分式"],
                        "warnings": [],
                        "regions": [
                            {
                                "role": "question",
                                "page_number": number,
                                "bbox": [0.1, 0.1, 0.9, 0.4],
                            }
                        ],
                    }
                    for item in items
                ]
            }
        )

    monkeypatch.setattr(organization, "infer_layouts", infer)
    organization.organize_document(structured["document"]["id"], run)
    result = client.get(f"/api/courses/{structured['course']['id']}/exercises").json()["items"]
    assert all(item["crop_status"] == "suggested" and not item["assets"] for item in result)
    assert all(item["question_type"] == "calculation" for item in result)


def test_manual_chapters_cancel_stale_worker_and_deleted_course_cannot_reappear(
    client, structured, db_engine, monkeypatch
):
    run = prepare_worker(db_engine, structured, monkeypatch)
    client.put(
        f"/api/documents/{structured['document']['id']}/chapters",
        json={
            "expected_version": 1,
            "chapters": [{"title": "我的章节", "start_page": 1, "end_page": 2}],
        },
    )
    organization.organize_document(structured["document"]["id"], run)
    assert client.get(structured["structure"]).json()["chapters"][0]["title"] == "我的章节"
    assert client.delete(f"/api/courses/{structured['course']['id']}").status_code == 204
    organization.organize_document(structured["document"]["id"], run)
    with Session(db_engine) as db:
        assert db.get(DocumentStructure, structured["document"]["id"]) is None
        assert not db.scalars(select(Chapter)).all()


def test_automatic_followup_preserves_existing_chapters(client, structured, db_engine, monkeypatch):
    run = prepare_worker(db_engine, structured, monkeypatch)
    organization.organize_document(structured["document"]["id"], run, preserve_chapters=True)
    state = client.get(structured["structure"]).json()
    assert state["version"] == 1
    assert [row["title"] for row in state["chapters"]] == ["第一章 分式", "第二章 运算"]


def test_text_only_model_can_label_without_receiving_images(
    client, structured, db_engine, monkeypatch
):
    settings = Settings(
        _env_file=None,
        llm_model="text-fixture",
        llm_api_key=SecretStr("fixed-test-key"),
        llm_base_url="https://models.example.com",
        llm_vision=False,
    )
    run = prepare_worker(db_engine, structured, monkeypatch, settings)
    seen = []

    def infer(number, items, image):
        assert image is None
        seen.extend(items)
        return PageLayouts.model_validate(
            {
                "exercises": [
                    {
                        "draft_id": item["draft_id"],
                        "question_type": "calculation",
                        "difficulty": "basic",
                        "knowledge_tags": ["分式"],
                        "warnings": [],
                        "regions": [],
                    }
                    for item in items
                ]
            }
        )

    monkeypatch.setattr(organization, "infer_layouts", infer)
    organization.organize_document(structured["document"]["id"], run)
    assert len(seen) == 2
    result = client.get(f"/api/courses/{structured['course']['id']}/exercises").json()["items"]
    assert all(item["question_type"] == "calculation" and not item["assets"] for item in result)


def test_assembly_balances_knowledge_and_honors_joint_quotas():
    def item(key, kind, level, tags):
        return {
            "draft_id": key,
            "question_type": kind,
            "difficulty": level,
            "knowledge_tags": tags,
            "question": "question " + key,
            "document_id": "doc",
            "chapter": {"id": "chapter"},
        }

    rows = [
        item("1", "choice", "basic", ["A"]),
        item("2", "choice", "advanced", ["B"]),
        item("3", "proof", "basic", ["C"]),
    ]
    selected = select_candidates(rows, 2, {"choice": 1, "proof": 1}, {"basic": 1, "advanced": 1})
    assert {row["draft_id"] for row in selected} == {"2", "3"}
    duplicate = {**rows[0], "draft_id": "copy"}
    assert len(select_candidates([rows[0], duplicate], 3, {}, {})) == 1


def test_assembly_is_scoped_reports_shortfalls_and_does_not_save(client, structured):
    path = f"/api/courses/{structured['course']['id']}/workbooks/assemble"
    result = client.post(
        path, json={"chapter_ids": [structured["chapters"][0]["id"]], "count": 3}
    ).json()
    assert result["report"]["selected"] == 1 and result["report"]["shortfall"] == 2
    assert client.get(structured["base"]).json() == []
    assert client.post(path, json={"chapter_ids": ["foreign"]}).status_code == 422
    assert (
        client.post(
            path, json={"count": 3, "type_counts": [{"question_type": "choice", "count": 2}]}
        ).status_code
        == 422
    )
    assert (
        client.post(path, json={"count": 2, "require_crops": True}).json()["report"]["selected"]
        == 0
    )


def test_semantic_assembly_only_accepts_whitelisted_existing_ids(client, structured, monkeypatch):
    calls = []
    foreign = False

    def complete(*args, response_model, **kwargs):
        calls.append(response_model)
        if response_model is AssemblyPlan:
            parsed = AssemblyPlan(
                title="原题复习",
                count=1,
                chapter_ids=[structured["chapters"][0]["id"]],
                type_counts=[],
                difficulty_counts=[],
                topics=["分式"],
                warnings=[],
            )
        else:
            assert response_model is SelectionOrder
            parsed = SelectionOrder(
                draft_ids=["not-in-pool" if foreign else structured["items"][0]["draft_id"]],
                explanation="覆盖分式计算。",
            )
        return LLMResponse("fixture", "", parsed, 1, 1)

    monkeypatch.setattr(workbook_assembly, "LLMClient", lambda: SimpleNamespace(complete=complete))
    path = f"/api/courses/{structured['course']['id']}/workbooks/assemble"
    response = client.post(path, json={"instructions": "第一章一道题"})
    assert response.status_code == 200 and response.json()["report"]["selected"] == 1
    foreign = True
    assert client.post(path, json={"instructions": "第一章一道题"}).status_code == 502
