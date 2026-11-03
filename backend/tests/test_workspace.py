from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pymupdf
import pytest
from app.core.auth import COOKIE_NAME, hash_token
from app.core.config import get_settings
from app.models import Document, ProcessingTask, User, UserSession
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session


def upload(client, course, content, filename="第一章.pdf", **data):
    return client.post(
        f"/api/courses/{course['id']}/documents",
        files={"file": (filename, content, "application/pdf")},
        data=data,
    )


def test_session_and_password_storage(client, account, db_engine):
    token = client.cookies.get(COOKIE_NAME)
    assert client.get("/api/auth/me").json()["id"] == account["id"]
    with Session(db_engine) as db:
        stored = db.get(User, account["id"])
        assert stored.password_hash.startswith("$argon2")
        assert stored.password_hash != "study-notes-2026"
        assert db.get(UserSession, hash_token(token)) is not None
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/auth/me").status_code == 401


def test_login_and_case_insensitive_email(client, account):
    client.post("/api/auth/logout")
    assert (
        client.post(
            "/api/auth/login",
            json={
                "email": "LIN@example.com",
                "password": "wrong-password",
            },
        ).status_code
        == 401
    )
    response = client.post(
        "/api/auth/login",
        json={
            "email": "LIN@example.com",
            "password": "study-notes-2026",
        },
    )
    assert response.status_code == 200
    assert response.json()["id"] == account["id"]
    assert "httponly" in response.headers["set-cookie"].lower()


def test_expired_session_is_rejected(client, account, db_engine):
    with Session(db_engine) as db:
        db.execute(update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_course_edit_and_counts(client, course, pdf_bytes):
    response = client.patch(
        f"/api/courses/{course['id']}",
        json={
            "name": "高等代数",
            "description": "第一学期",
            "color": "blue",
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == "高等代数"
    assert upload(client, course, pdf_bytes).status_code == 201
    assert client.get("/api/courses").json()[0]["document_count"] == 1
    assert client.get(f"/api/courses/{course['id']}").json()["document_count"] == 1


def test_pdf_upload_source_and_preferences(client, course, pdf_bytes):
    response = upload(client, course, pdf_bytes, exercise_mode="original")
    assert response.status_code == 201
    document = response.json()
    assert document["page_count"] == 2
    assert document["exercise_mode"] == "original"
    assert document["task"]["stage"] == "awaiting_extraction"
    assert document["task"]["status"] == "pending"
    assert "storage_key" not in document
    source = client.get(f"/api/documents/{document['id']}/file")
    assert source.content == pdf_bytes
    assert (
        "private" in source.headers.get("cache-control", "")
        or source.headers["cache-control"] == "no-store"
    )
    tasks = client.get("/api/tasks").json()
    assert tasks[0]["filename"] == "第一章.pdf"
    assert tasks[0]["course_id"] == course["id"]
    assert client.get(f"/api/tasks/{tasks[0]['id']}").status_code == 200


def test_all_resources_are_scoped_to_owner(client, course, pdf_bytes):
    document = upload(client, course, pdf_bytes).json()
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={
            "email": "other@example.com",
            "name": "另一位同学",
            "password": "another-account",
        },
    )
    assert client.get("/api/courses").json() == []
    assert client.get("/api/tasks").json() == []
    paths = [
        f"/api/courses/{course['id']}",
        f"/api/courses/{course['id']}/documents",
        f"/api/documents/{document['id']}/file",
        f"/api/tasks/{document['task']['id']}",
    ]
    for path in paths:
        assert client.get(path).status_code == 404
    assert client.delete(f"/api/courses/{course['id']}").status_code == 404
    assert client.delete(f"/api/documents/{document['id']}").status_code == 404
    assert upload(client, course, pdf_bytes).status_code == 404
    assert client.patch(f"/api/courses/{course['id']}", json={"name": "改名"}).status_code == 404


@pytest.mark.parametrize(
    "filename,content",
    [("notes.txt", b"text"), ("fake.pdf", b"not a pdf"), ("broken.pdf", b"%PDF-1.7\nbroken")],
)
def test_invalid_uploads_leave_no_files(client, course, filename, content):
    assert upload(client, course, content, filename).status_code == 422
    assert client.get(f"/api/courses/{course['id']}/documents").json() == []
    assert list(get_settings().storage_path.rglob("*.pdf")) == []


def test_encrypted_pdf_is_rejected(client, course):
    with pymupdf.open() as document:
        document.new_page()
        encrypted = document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader"
        )
    assert upload(client, course, encrypted).status_code == 422


def test_size_limit_and_invalid_preferences(client, course, pdf_bytes, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    assert upload(client, course, b"%PDF-" + b"x" * 1024 * 1024).status_code == 413
    assert upload(client, course, pdf_bytes, exercise_mode="unknown").status_code == 422
    assert list(get_settings().storage_path.rglob("*.pdf")) == []


def test_filename_cannot_escape_storage(client, course, pdf_bytes):
    response = upload(client, course, pdf_bytes, "../../outside.pdf")
    assert response.status_code == 201
    assert response.json()["filename"] == "outside.pdf"
    files = list(get_settings().storage_path.rglob("*.pdf"))
    assert len(files) == 1
    assert files[0].name != "outside.pdf"


def test_failed_database_write_removes_uploaded_file(client, course, pdf_bytes):
    with (
        patch("sqlalchemy.orm.Session.commit", side_effect=RuntimeError("write failed")),
        pytest.raises(RuntimeError, match="write failed"),
    ):
        upload(client, course, pdf_bytes)
    assert list(get_settings().storage_path.rglob("*.pdf")) == []
    assert client.get(f"/api/courses/{course['id']}/documents").json() == []


def test_delete_cleans_files_and_dependent_records(client, course, pdf_bytes, db_engine):
    first = upload(client, course, pdf_bytes).json()
    assert client.delete(f"/api/documents/{first['id']}").status_code == 204
    assert client.get(f"/api/tasks/{first['task']['id']}").status_code == 404
    upload(client, course, pdf_bytes)
    assert client.delete(f"/api/courses/{course['id']}").status_code == 204
    assert list(get_settings().storage_path.rglob("*.pdf")) == []
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(Document.id))) == 0
        assert db.scalar(select(func.count(ProcessingTask.id))) == 0


def test_auth_required_and_foreign_origin_rejected(client):
    assert client.get("/api/courses").status_code == 401
    assert (
        client.post(
            "/api/auth/register", headers={"Origin": "http://127.0.0.1:8000"}, json={}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/login",
            headers={"Origin": "https://other.example"},
            json={"email": "lin@example.com", "password": "test-password"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/auth/register",
            json={
                "email": "bad",
                "name": " ",
                "password": "short",
            },
        ).status_code
        == 422
    )
