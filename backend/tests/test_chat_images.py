import io
from uuid import uuid4

import pytest
from app.core.config import get_settings
from app.models import ChatImage, ChatMessage, Conversation
from app.schemas.chat import ChatPlan, ConversationDraft, ImageObservation
from app.services import chat, chat_images
from app.services.llm import LLMResponse
from app.services.model_api import ModelAPIError
from PIL import Image
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from test_chat import answer_fixture, ask, thread
from test_chat_branches import fork
from test_knowledge import create


def png(color="white", size=(64, 48), format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=format)
    return output.getvalue()


def upload(
    client,
    path,
    content="请解释图片",
    request_id=None,
    data=None,
    name="截图.png",
    media_type="image/png",
    count=1,
):
    return client.post(
        path + "/messages/with-images",
        data={
            "content": content,
            "request_id": request_id or str(uuid4()),
        },
        files=[
            ("files", (name, data if data is not None else png(), media_type)) for _ in range(count)
        ],
    )


def response(parsed):
    return LLMResponse("image-test-model", parsed.model_dump_json(), parsed, 10, 5)


@pytest.fixture
def visual(monkeypatch):
    calls = {"describe": 0, "answer": 0, "images": []}

    def describe(question, images):
        calls["describe"] += 1
        assert images and all(data.startswith(b"\x89PNG") for data in images)
        return response(
            ImageObservation(description="固定测试图片：矩形示意图，长 3、宽 2。", warnings=[])
        )

    def plan(question, history, evidence, memory):
        assert memory["has_images"]
        return response(ChatPlan(route="image", query=""))

    def converse(question, history, route, memory, *, images=None):
        calls["answer"] += 1
        calls["images"] = images
        assert route == "image" and images
        return response(
            ConversationDraft(
                answer="图片给出的条件是长 3、宽 2，可得面积 $3\\times2=6$。",
                needs_retrieval=False,
                query="",
            )
        )

    monkeypatch.setattr(chat, "describe_images", describe)
    monkeypatch.setattr(chat, "plan_question", plan)
    monkeypatch.setattr(chat, "generate_conversation", converse)
    return calls


def test_image_only_message_persists_private_images_and_text_observation(
    client, course, db_engine, visual, monkeypatch
):
    def forbidden(*args):
        pytest.fail("Visual questions must not force course retrieval")

    monkeypatch.setattr("app.services.chat_graph.retrieve_course", forbidden)
    root, path = thread(client, course)
    result = upload(client, path, content="")
    assert result.status_code == 200, result.text
    assert result.json()["retrieval_mode"] == "image" and not result.json()["citations"]
    rows = client.get(path + "/messages").json()
    assert len(rows) == 2 and rows[0]["content"] == ""
    image = rows[0]["images"][0]
    assert image["filename"] == "截图.png" and image["width"] == 64
    assert "data" not in image and "image_context" not in rows[0]
    assert client.get(f"/api/chat/images/{image['id']}").status_code == 200
    with Session(db_engine) as db:
        assert "矩形" in db.get(ChatMessage, rows[0]["id"]).image_context
        assert db.get(Conversation, root["id"]).title == "图片提问"
        blobs = db.execute(
            text("SELECT blob FROM checkpoint_blobs WHERE blob IS NOT NULL")
        ).scalars()
        assert all(
            b"\x89PNG\r\n\x1a\n" not in bytes(blob) and b"data:image/" not in bytes(blob)
            for blob in blobs
        )
    assert visual["describe"] == visual["answer"] == 1


def test_multimodal_message_idempotency_and_retry_reuse_saved_images(
    client, course, db_engine, visual, monkeypatch
):
    _root, path = thread(client, course)
    request_id = str(uuid4())

    def fail(*args, **kwargs):
        raise ModelAPIError("private provider body")

    good = chat.generate_conversation
    monkeypatch.setattr(chat, "generate_conversation", fail)
    assert upload(client, path, request_id=request_id).status_code == 502
    assert len(client.get(path + "/messages").json()[0]["images"]) == 1
    monkeypatch.setattr(chat, "generate_conversation", good)
    result = ask(client, path, "请解释图片", request_id)
    assert result.status_code == 200, result.text
    assert visual["describe"] == 1 and visual["answer"] == 1
    assert upload(client, path, request_id=request_id).json()["id"] == result.json()["id"]
    assert upload(client, path, request_id=request_id, data=png("red")).status_code == 409
    assert len(client.get(path + "/messages").json()) == 2
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(ChatImage.id))) == 1


def test_image_authentication_and_course_isolation(client, course, visual):
    _root, path = thread(client, course)
    assert upload(client, path).status_code == 200
    image_id = client.get(path + "/messages").json()[0]["images"][0]["id"]
    other = client.post("/api/courses", json={"name": "另一门课"}).json()
    assert upload(client, path.replace(course["id"], other["id"])).status_code == 404
    client.post("/api/auth/logout")
    assert client.get(f"/api/chat/images/{image_id}").status_code == 401
    client.post(
        "/api/auth/register",
        json={
            "name": "其他用户",
            "email": "other-images@example.com",
            "password": "another-password",
        },
    )
    assert client.get(f"/api/chat/images/{image_id}").status_code == 404
    assert upload(client, path).status_code == 404
    assert visual["describe"] == 1


@pytest.mark.parametrize(
    "case,status",
    [("fake", 422), ("unsupported", 422), ("oversize", 413), ("too_many", 422), ("pixels", 413)],
)
def test_invalid_images_are_rejected_before_messages_or_model_calls(
    client, course, db_engine, monkeypatch, case, status
):
    _root, path = thread(client, course)
    if case == "pixels":
        monkeypatch.setattr(chat_images, "MAX_PIXELS", 100)
    result = upload(
        client,
        path,
        data=b"not an image"
        if case == "fake"
        else (b"x" * (chat_images.MAX_BYTES + 1) if case == "oversize" else png()),
        media_type="image/svg+xml" if case == "unsupported" else "image/png",
        count=5 if case == "too_many" else 1,
    )
    assert result.status_code == status, result.text
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(ChatMessage.id))) == 0
        assert db.scalar(select(func.count(ChatImage.id))) == 0


def test_unsupported_vision_rejects_images_but_keeps_text_chat(
    client, course, monkeypatch, db_engine
):
    monkeypatch.setattr(get_settings(), "llm_vision", False)
    _root, path = thread(client, course)
    result = upload(client, path)
    assert result.status_code == 422 and "未启用图片识别" in result.json()["detail"]
    assert ask(client, path, "纯文字问题").status_code == 200
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(ChatImage.id))) == 0


@pytest.mark.parametrize("delete_course", [False, True])
def test_image_deletion_follows_message_course_and_branch_lifecycle(
    client, course, db_engine, visual, delete_course
):
    _root, path = thread(client, course)
    answer = upload(client, path).json()
    image_id = client.get(path + "/messages").json()[0]["images"][0]["id"]
    _branch, branch_path, body = fork(client, path, answer, question="再解释图中的条件")
    assert ask(client, branch_path, body["question"], body["request_id"]).status_code == 200
    assert visual["describe"] == 1 and visual["answer"] == 2
    assert client.delete(branch_path).status_code == 204
    assert client.get(f"/api/chat/images/{image_id}").status_code == 200
    assert (
        client.delete(f"/api/courses/{course['id']}" if delete_course else path).status_code == 204
    )
    assert client.get(f"/api/chat/images/{image_id}").status_code == 404
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(ChatImage.id))) == 0


def test_text_followup_and_course_retrieval_can_use_original_image(
    client, course, visual, monkeypatch
):
    _root, path = thread(client, course)
    assert upload(client, path).status_code == 200
    assert ask(client, path, "图中另一边是多少？").status_code == 200
    assert visual["describe"] == 1 and visual["answer"] == 2
    create(client, course)
    monkeypatch.setattr(
        chat,
        "plan_question",
        lambda *args: response(ChatPlan(route="retrieve", query="线性无关定义")),
    )

    def generate(question, history, context):
        assert context.images and "矩形" in history[0]["content"]
        return answer_fixture(question, history, context)

    monkeypatch.setattr(chat, "generate_answer", generate)
    result = ask(client, path, "结合课件定义解释一下")
    assert result.status_code == 200 and result.json()["citations"]


def test_jpeg_and_webp_are_decoded_and_exif_is_removed(client, course, visual):
    _root, path = thread(client, course)
    for format, name, mime in [
        ("JPEG", "photo.jpg", "image/jpeg"),
        ("WEBP", "photo.webp", "image/webp"),
    ]:
        result = upload(client, path, data=png(format=format), name=name, media_type=mime)
        assert result.status_code == 200, result.text
    source = Image.new("RGB", (40, 20), "white")
    metadata = Image.Exif()
    metadata[270] = "private device metadata"
    metadata[274] = 6
    stream = io.BytesIO()
    source.save(stream, format="JPEG", exif=metadata)
    assert (
        upload(
            client, path, data=stream.getvalue(), name="rotated.jpg", media_type="image/jpeg"
        ).status_code
        == 200
    )
    image = client.get(path + "/messages").json()[-2]["images"][0]
    saved = client.get(f"/api/chat/images/{image['id']}").content
    assert b"private device metadata" not in saved
    assert image["width"] == 20 and image["height"] == 40
