from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.schemas.chat import ChatPlan
from app.services import chat
from app.services.llm import LLMResponse
from app.services.query_embeddings import clear_query_cache
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema


@pytest.fixture
def db_engine(tmp_path):
    test_url = get_settings().test_database_url
    if not test_url:
        raise ValueError(
            "Configure TEST_DATABASE_URL with a PostgreSQL test database ending in _test"
        )
    url = make_url(test_url)
    if url.get_backend_name() != "postgresql" or not (url.database or "").endswith("_test"):
        raise ValueError("TEST_DATABASE_URL must name a PostgreSQL database ending in _test")
    admin = create_engine(test_url)
    schema = "test_" + uuid4().hex
    with admin.begin() as connection:
        connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        connection.execute(CreateSchema(schema))
    engine = create_engine(test_url)

    @event.listens_for(engine, "connect")
    def search_path(connection, _):
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        connection.commit()

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


@pytest.fixture
def client(db_engine, tmp_path, monkeypatch):
    sessions = sessionmaker(bind=db_engine, expire_on_commit=False)

    def override_db():
        with sessions() as session:
            yield session

    monkeypatch.setattr(get_settings(), "storage_path", tmp_path / "storage")
    monkeypatch.setattr(get_settings(), "app_mode", "multiuser")
    monkeypatch.setattr(get_settings(), "extraction_auto_start", False)
    monkeypatch.setattr(get_settings(), "document_auto_organize", False)
    monkeypatch.setattr(get_settings(), "embedding_auto_index", False)
    monkeypatch.setattr(
        chat,
        "plan_question",
        lambda question, history, evidence, memory: LLMResponse(
            None, "", ChatPlan(route="retrieve", query=""), 0, 0
        ),
    )
    clear_query_cache()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def pdf_bytes():
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Chapter 1: Linear algebra")
        document.new_page().insert_text((72, 72), "Vectors and matrices")
        return document.tobytes()


@pytest.fixture
def account(client):
    response = client.post(
        "/api/auth/register",
        json={
            "name": "小林",
            "email": "lin@example.com",
            "password": "study-notes-2026",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def course(client, account):
    response = client.post(
        "/api/courses",
        json={
            "name": "线性代数",
            "description": "矩阵与线性变换",
            "color": "sage",
        },
    )
    assert response.status_code == 201
    return response.json()
