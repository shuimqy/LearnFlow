import hashlib
import json
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from app.core.config import get_settings
from app.models import KnowledgeChunk, PageExtraction
from app.services.course_package import export_course_package, validate_course_package
from app.services.storage import storage_file
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_exercise_crops import layout_input
from test_knowledge import create, upload
from test_workbooks import exercises as exercises  # noqa: PLC0414


def replace_member(members, name, content):
    manifest = json.loads(members["manifest.json"])
    manifest["files"][name] = {
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    with BytesIO() as buffer:
        with ZipFile(buffer, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            for member, original in members.items():
                if member != "manifest.json":
                    archive.writestr(member, content if member == name else original)
        return buffer.getvalue()


def test_package_checks_course_ownership_and_chunk_hashes(
    client, course, account, pdf_bytes, db_engine, tmp_path
):
    document = upload(client, course, pdf_bytes)
    create(client, course, sources=[{"document_id": document["id"], "page_number": 2}])
    output = tmp_path / "course.zip"
    with Session(db_engine) as db:
        with pytest.raises(ValueError, match="Course not found for this owner"):
            export_course_package(db, course["id"], "unrelated-user", output)
        assert not output.exists()
        export_course_package(db, course["id"], account["id"], output)

    report = validate_course_package(output)
    assert (report["documents"], report["pdf_pages"], report["knowledge"], report["chunks"]) == (
        1,
        2,
        1,
        1,
    )
    assert report["embedding"]["indexes"] == []

    with ZipFile(output) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    data = json.loads(members["chunks.jsonl"])
    data["content_sha256"] = "0" * 64
    tampered = tmp_path / "tampered.zip"
    tampered.write_bytes(replace_member(members, "chunks.jsonl", json.dumps(data).encode() + b"\n"))
    with pytest.raises(ValueError, match="Chunk hashes do not match"):
        validate_course_package(tampered)


def test_course_package_api_restores_private_course_and_rolls_back_invalid_pdf(
    client, course, exercises, pdf_bytes, db_engine, monkeypatch
):
    original = f"/api/courses/{course['id']}"
    document_id = exercises["document"]["id"]
    item = exercises["items"][0]
    original_exercise = original + f"/exercises/{item['draft_id']}"
    assert client.put(original_exercise + "/layout", json=layout_input()).status_code == 200
    asset = client.get(original_exercise).json()["assets"][1]
    original_image = client.get(original_exercise + f"/assets/{asset['id']}").content
    chapter = {"title": "第一章", "start_page": 1, "end_page": 2}
    assert (
        client.put(
            f"/api/documents/{document_id}/chapters",
            json={"expected_version": 0, "chapters": [chapter]},
        ).status_code
        == 200
    )
    reference = create(client, course, sources=[{"document_id": document_id, "page_number": 2}])
    exported = client.get(original + "/export")
    assert exported.status_code == 200, exported.text[:100]
    assert exported.headers["content-disposition"].startswith("attachment;")

    client.post("/api/auth/logout")
    assert client.get(original + "/export").status_code == 401
    assert (
        client.post(
            "/api/auth/register",
            json={"name": "小陈", "email": "chen@example.com", "password": "study-notes-2026"},
        ).status_code
        == 201
    )
    assert client.get(original + "/export").status_code == 404
    assert client.get(f"/api/documents/{document_id}/file").status_code == 404

    def fail_enqueue(_):
        pytest.fail("Import must leave Embedding to the receiving account")

    monkeypatch.setattr(get_settings(), "embedding_auto_index", True)
    monkeypatch.setattr("app.services.vector_index.enqueue_index", fail_enqueue)
    request = {"request_id": str(uuid4())}

    def post(content):
        return client.post(
            "/api/courses/import", files={"file": ("course.zip", content)}, data=request
        )

    with ZipFile(BytesIO(exported.content)) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    before = set(storage_file("documents").glob("*.pdf"))
    invalid = replace_member(members, f"files/documents/{document_id}.pdf", b"no PDF content")
    assert post(invalid).status_code == 422
    assert client.get("/api/courses").json() == []
    assert set(storage_file("documents").glob("*.pdf")) == before

    imported = post(exported.content)
    assert imported.status_code == 201, imported.text
    new = imported.json()
    assert new["id"] != course["id"] and new["name"] == course["name"]
    assert new["document_count"] == 1
    assert post(exported.content).json()["id"] == new["id"]
    assert client.get("/api/courses").json() == [new]

    base = f"/api/courses/{new['id']}"
    document = client.get(base + "/documents").json()[0]
    assert document["id"] != document_id
    assert document["task"]["status"] == "completed"
    assert client.get(f"/api/documents/{document['id']}/file").content == pdf_bytes
    chapters = client.get(base + "/chapters").json()
    assert [(c["title"], c["document_id"]) for c in chapters] == [
        (chapter["title"], document["id"])
    ]
    (point,) = client.get(base + "/knowledge").json()
    assert point["title"] == reference["title"]
    assert client.get(base + "/knowledge/stats").json()["active"] == 1
    assert client.get(base + "/knowledge", params={"q": "题目"}).json() == []
    assert point["id"] != reference["id"]
    assert point["sources"][0]["document_id"] == document["id"]
    assert point["sources"][0]["page_number"] == 2

    items = client.get(base + "/exercises").json()["items"]
    assert {i["kind"] for i in items} == {"exercise", "worked_example"}
    exercise = next(i for i in items if i["kind"] == item["kind"])
    assert client.get(base + f"/knowledge/{exercise['knowledge_id']}").status_code == 200
    assert exercise["draft_id"] != item["draft_id"]
    assert exercise["crop_status"] == "confirmed"
    assert exercise["chapter"]["id"] == chapters[0]["id"]
    new_asset = next(a for a in exercise["assets"] if a["role"] == asset["role"])
    assert new_asset["id"] != asset["id"]
    image = client.get(base + f"/exercises/{exercise['draft_id']}/assets/{new_asset['id']}")
    assert image.status_code == 200 and image.content == original_image

    with Session(db_engine) as db:
        chunks = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.course_id == new["id"]))
        assert [(c.embedding_status, c.embedding) for c in chunks] == [("pending", None)] * 3
        pages = db.scalars(
            select(PageExtraction)
            .where(PageExtraction.document_id == document["id"])
            .order_by(PageExtraction.page_number)
        )
        assert [(p.page_number, p.transcript) for p in pages] == [
            (1, "synthetic exercise"),
            (2, "synthetic exercise"),
        ]
