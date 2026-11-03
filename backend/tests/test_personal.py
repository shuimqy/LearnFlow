from concurrent.futures import ThreadPoolExecutor

import pytest
from app.core.auth import COOKIE_NAME
from app.core.config import Settings, get_settings
from app.core.personal import PERSONAL_USER_ID, personal_user
from app.models import User, UserSession
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@pytest.fixture
def personal(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_mode", "personal")
    return client


def test_personal_workspace_needs_no_cookie_and_persists_identity(personal, db_engine):
    first = personal.get("/api/auth/me")
    assert first.status_code == 200
    assert first.json()["mode"] == "personal"
    assert first.json()["id"] == PERSONAL_USER_ID
    assert "set-cookie" not in first.headers
    assert "password_hash" not in first.text
    course = personal.post("/api/courses", json={"name": "本地课程", "color": "sage"}).json()
    personal.cookies.clear()
    assert personal.get("/api/auth/me").json()["id"] == first.json()["id"]
    assert personal.get("/api/courses").json()[0]["id"] == course["id"]
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(User.id))) == 1
        assert db.scalar(select(func.count(UserSession.token_hash))) == 0


def test_concurrent_first_access_creates_one_local_identity(db_engine):
    def access(_):
        with Session(db_engine) as db:
            return personal_user(db).id

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(access, range(8))) == {PERSONAL_USER_ID}
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(User.id))) == 1


@pytest.mark.parametrize("action", ["register", "login", "logout"])
def test_personal_rejects_auth_actions(personal, action):
    response = personal.post(
        f"/api/auth/{action}",
        json={"email": "new@example.com", "password": "valid-password", "name": "新用户"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "untrusted.example"},
        {"Origin": "https://untrusted.example"},
        {"Origin": "null"},
        {"X-Forwarded-Host": "untrusted.example"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_personal_rejects_nonlocal_browser_requests(personal, headers, db_engine):
    assert personal.get("/api/auth/me", headers=headers).status_code == 403
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(User.id))) == 0


def test_personal_rejects_remote_network_client(personal):
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1", client=("192.168.1.10", 50000)) as remote:
        assert remote.get("/api/auth/me").status_code == 403


def test_personal_keeps_account_files_and_courses_isolated(client, course, pdf_bytes, monkeypatch):
    document = client.post(
        f"/api/courses/{course['id']}/documents",
        files={"file": ("notes.pdf", pdf_bytes, "application/pdf")},
    ).json()
    cookie = client.cookies.get(COOKIE_NAME)
    monkeypatch.setattr(get_settings(), "app_mode", "personal")
    assert client.get("/api/auth/me").json()["id"] == PERSONAL_USER_ID
    assert client.get("/api/courses").json() == []
    for path in [
        f"/api/courses/{course['id']}",
        f"/api/courses/{course['id']}/knowledge",
        f"/api/documents/{document['id']}/file",
        f"/api/tasks/{document['task']['id']}",
    ]:
        assert client.get(path).status_code == 404
    local = client.post("/api/courses", json={"name": "单机课程", "color": "sage"}).json()
    monkeypatch.setattr(get_settings(), "app_mode", "multiuser")
    assert client.cookies.get(COOKIE_NAME) == cookie
    assert client.get("/api/auth/me").json()["mode"] == "multiuser"
    assert [item["id"] for item in client.get("/api/courses").json()] == [course["id"]]
    assert client.get(f"/api/courses/{local['id']}").status_code == 404
    client.cookies.clear()
    assert client.get("/api/courses").status_code == 401


def test_personal_upload_knowledge_and_models_are_available(personal, pdf_bytes):
    course = personal.post("/api/courses", json={"name": "线性代数", "color": "sage"}).json()
    document = personal.post(
        f"/api/courses/{course['id']}/documents",
        files={"file": ("notes.pdf", pdf_bytes, "application/pdf")},
    )
    assert document.status_code == 201
    point = personal.post(
        f"/api/courses/{course['id']}/knowledge",
        json={"title": "向量", "content": "向量可以进行线性组合。"},
    )
    assert point.status_code == 201
    assert personal.get("/api/account/models").status_code == 200
    assert personal.get(f"/api/courses/{course['id']}/knowledge").status_code == 200


def test_unknown_mode_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_mode="unknown")
