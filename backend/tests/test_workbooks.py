import copy
import subprocess
from types import SimpleNamespace

import pymupdf
import pytest
from app.api import workbooks as workbook_api
from app.models import ExtractionDraft, KnowledgePoint, PageExtraction, Workbook
from app.services import workbook_pdf
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_knowledge import create, upload


@pytest.fixture
def exercises(client, course, pdf_bytes, db_engine):
    document = upload(client, course, pdf_bytes)
    points = [create(client, course, title=f"题目 {i}") for i in (1, 2)]
    with Session(db_engine) as db:
        for i, point in enumerate(points, 1):
            page = PageExtraction(
                document_id=document["id"],
                page_number=i,
                status="completed",
                transcript="synthetic exercise",
                warnings=[],
            )
            db.add(page)
            db.flush()
            db.add(
                ExtractionDraft(
                    extraction_id=page.id,
                    position=0,
                    kind="exercise" if i == 1 else "worked_example",
                    title=f"题目 {i}",
                    summary="",
                    content=f"Question {i}",
                    formulas=[],
                    warnings=[],
                    status="imported",
                    knowledge_id=point["id"],
                    example={
                        "question": f"计算 $\\frac{{{i * 4}}}{{2}}$。",
                        "answer": str(i * 2) if i == 1 else "",
                        "solution": "Divide by two." if i == 1 else "",
                        "warnings": [],
                    },
                )
            )
        db.commit()
    result = client.get(f"/api/courses/{course['id']}/exercises").json()
    return {
        "document": document,
        "points": points,
        "items": result["items"],
        "base": f"/api/courses/{course['id']}/workbooks",
    }


def payload(exercises, **changes):
    return {
        "title": "第一章练习",
        "expected_version": 0,
        "sections": [{"title": "分式", "items": exercises["items"]}],
        "settings": {"include_answers": True, "answer_space": "medium", "show_sources": True},
        **changes,
    }


def save(client, exercises, **changes):
    response = client.post(exercises["base"], json=payload(exercises, **changes))
    assert response.status_code == 201, response.text
    return response.json()


def test_filters_only_return_course_original_exercises(client, course, exercises):
    path = f"/api/courses/{course['id']}/exercises"
    assert len(exercises["items"]) == 2
    result = client.get(
        path,
        params={
            "document_id": exercises["document"]["id"],
            "page_from": 2,
            "page_to": 2,
            "kind": "worked_example",
        },
    ).json()
    assert result["total"] == 1 and result["items"][0]["page_number"] == 2
    assert client.get(path, params={"kind": "exercise"}).json()["total"] == 1
    assert client.get(path, params={"query": "题目 1"}).json()["total"] == 1
    assert client.get(path, params={"query": "%"}).json()["total"] == 0
    assert client.get(path, params={"page_from": 3, "page_to": 1}).status_code == 422
    assert client.get(path, params={"limit": 1, "offset": 1}).json()["items"][0]["page_number"] == 2


def test_workbook_snapshots_order_edits_and_version_guards(client, course, exercises, db_engine):
    request = payload(exercises)
    request["sections"][0]["items"] = list(reversed(copy.deepcopy(exercises["items"])))
    request["sections"][0]["items"][0]["question"] = "本册修改后的题目 $x^2$"
    request["sections"][0]["items"][0]["filename"] = "fake-source.pdf"
    response = client.post(exercises["base"], json=request)
    assert response.status_code == 201, response.text
    book = response.json()
    assert book["sections"][0]["items"][0]["page_number"] == 2
    assert book["sections"][0]["items"][0]["filename"] == "lecture.pdf"
    assert client.get(exercises["base"]).json()[0]["id"] == book["id"]
    update = {**book, "expected_version": 1, "title": "修订版"}
    path = exercises["base"] + "/" + book["id"]
    assert client.put(path, json=update).json()["version"] == 2
    assert client.put(path, json=update).status_code == 409
    assert client.get(path).json()["title"] == "修订版"
    with Session(db_engine) as db:
        assert db.get(KnowledgePoint, exercises["points"][1]["id"]).version == 1
        assert "本册修改" not in db.get(KnowledgePoint, exercises["points"][1]["id"]).content
    assert client.delete(path).status_code == 204
    assert client.get(path).status_code == 404


def test_new_selection_detects_changed_knowledge_and_keeps_warnings(
    client, course, exercises, db_engine
):
    with Session(db_engine) as db:
        point = db.get(KnowledgePoint, exercises["points"][0]["id"])
        point.version += 1
        db.commit()
    assert client.post(exercises["base"], json=payload(exercises)).status_code == 409
    refreshed = client.get(f"/api/courses/{course['id']}/exercises").json()["items"]
    assert "已修订" in refreshed[0]["warnings"][0]
    exercises["items"] = refreshed
    book = save(client, exercises)
    assert book["sections"][0]["items"][0]["warnings"]


def test_workbook_survives_deleted_source_and_course_deletion_cascades(
    client, course, exercises, db_engine
):
    book = save(client, exercises)
    path = exercises["base"] + "/" + book["id"]
    assert client.delete(f"/api/documents/{exercises['document']['id']}").status_code == 204
    assert client.get(f"/api/courses/{course['id']}/exercises").json()["total"] == 0
    update = {**book, "expected_version": 1}
    assert client.put(path, json=update).status_code == 200
    assert client.get(path).json()["sections"][0]["items"][0]["filename"] == "lecture.pdf"
    assert client.delete(f"/api/courses/{course['id']}").status_code == 204
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(Workbook.id))) == 0


def test_workbook_and_source_ownership(client, course, exercises):
    book = save(client, exercises)
    other = client.post("/api/courses", json={"name": "另一门课"}).json()
    other_base = f"/api/courses/{other['id']}"
    assert client.post(other_base + "/workbooks", json=payload(exercises)).status_code == 404
    assert (
        client.get(other_base + f"/exercises?document_id={exercises['document']['id']}").status_code
        == 404
    )
    assert client.get(other_base + f"/workbooks/{book['id']}").status_code == 404
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={
            "name": "其他账号",
            "email": "workbook-other@example.com",
            "password": "workbook-password",
        },
    )
    path = exercises["base"] + "/" + book["id"]
    assert client.get(exercises["base"]).status_code == 404
    assert client.get(f"/api/courses/{course['id']}/exercises").status_code == 404
    assert client.get(path).status_code == 404
    assert client.put(path, json={**book, "expected_version": 1}).status_code == 404
    assert client.delete(path).status_code == 404
    assert client.get(path + "/pdf?version=1").status_code == 404


@pytest.mark.parametrize("change", ["empty", "duplicate", "blank", "too_many"])
def test_invalid_workbooks_are_rejected(client, exercises, change):
    request = payload(exercises)
    if change == "empty":
        request["sections"] = []
    if change == "duplicate":
        request["sections"][0]["items"] *= 2
    if change == "blank":
        request["sections"][0]["items"][0] = {**exercises["items"][0], "question": "   "}
    if change == "too_many":
        request["sections"][0]["items"] = [
            {**exercises["items"][0], "draft_id": str(i)} for i in range(101)
        ]
    assert client.post(exercises["base"], json=request).status_code == 422


def test_pdf_download_uses_saved_version_and_owner_scope(client, exercises, monkeypatch):
    book = save(client, exercises)
    seen = []

    def render(snapshot):
        seen.append(snapshot)
        return b"%PDF-synthetic"

    monkeypatch.setattr(workbook_api, "render_workbook_pdf", render)
    path = exercises["base"] + "/" + book["id"] + "/pdf"
    assert client.get(path + "?version=2").status_code == 409
    assert not seen
    response = client.get(path + "?version=1")
    assert response.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    assert seen[0]["sections"][0]["items"][0]["question"] == exercises["items"][0]["question"]


def test_pdf_renderer_errors_are_safe_and_release_slots(monkeypatch):
    monkeypatch.setattr(workbook_pdf.shutil, "which", lambda name: "node")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("private content", 90)

    monkeypatch.setattr(workbook_pdf.subprocess, "run", timeout)
    with pytest.raises(HTTPException) as error:
        workbook_pdf.render_workbook_pdf({})
    assert error.value.status_code == 504
    assert "private" not in error.value.detail
    monkeypatch.setattr(
        workbook_pdf.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout=b"", stderr=b"private question or key"
        ),
    )
    with pytest.raises(HTTPException) as error:
        workbook_pdf.render_workbook_pdf({})
    assert error.value.status_code == 503 and "private" not in error.value.detail
    monkeypatch.setattr(
        workbook_pdf.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b"%PDF-ok"),
    )
    assert workbook_pdf.render_workbook_pdf({}) == b"%PDF-ok"


def test_real_pdf_renders_chinese_math_and_separate_answers(tmp_path):
    snapshot = {
        "title": "分式做题本",
        "course_name": "线性代数",
        "sections": [
            {
                "title": "第一章",
                "items": [
                    {
                        "title": "分式计算",
                        "question": "求 $\\frac{4}{2}$。\n\n![题图](https://never-fetch.invalid/image.png)\n<script>alert('x')</script>",
                        "answer": "ANSWER_SECRET_42",
                        "solution": "分子除以分母。",
                        "filename": "lecture.pdf",
                        "page_number": 1,
                        "warnings": ["请核对题图"],
                    }
                ],
            }
        ],
        "settings": {"include_answers": True, "show_sources": True, "answer_space": "page"},
    }
    data = workbook_pdf.render_workbook_pdf(snapshot)
    target = tmp_path / "workbook.pdf"
    target.write_bytes(data)
    with pymupdf.open(stream=data, filetype="pdf") as pdf:
        assert len(pdf) >= 2
        assert "ANSWER_SECRET_42" not in pdf[0].get_text()
        text = "\n".join(page.get_text() for page in pdf)
        assert "分式做题本" in text and "第一章" in text
        assert "ANSWER_SECRET_42" in text and "lecture.pdf" in text
        assert "alert('x')" not in text
        assert pdf[0].get_fonts()
    snapshot["settings"]["include_answers"] = False
    with pymupdf.open(stream=workbook_pdf.render_workbook_pdf(snapshot), filetype="pdf") as pdf:
        assert "ANSWER_SECRET_42" not in "\n".join(page.get_text() for page in pdf)
