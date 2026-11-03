from types import SimpleNamespace

import httpx
import pytest
from app.core.config import Settings
from app.models import KnowledgeChunk, KnowledgeRevision
from app.schemas.knowledge import KnowledgeUpdate
from app.schemas.proposal_review import ProposalReview
from app.services import proposal_processing, proposal_review
from app.services.knowledge import find_knowledge, update_knowledge
from app.services.llm import LLMClient
from app.services.model_api import ModelAPIError
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_knowledge import base, create, payload, search, upload


def approved_response(current, proposed, reason, sources, images, limited):
    return make_response(proposed)


def make_response(proposed, **changes):
    review = ProposalReview.model_validate(
        {
            "verdict": "approve",
            "basis": "reasoning",
            "opinion": "建议补全了判断条件，可以采纳。",
            "reasons": ["检查定义与条件后，建议中的结论成立。"],
            "changes": ["补充判断条件。"],
            "warnings": [],
            "evidence": [],
            **{key: proposed[key] for key in ("title", "summary", "content")},
            **changes,
        }
    )
    return SimpleNamespace(parsed=review, model="qwen3.8-flash", input_tokens=100, output_tokens=50)


def suggestion(client, course, **changes):
    point = create(client, course)
    path = base(course) + "/" + point["id"]
    data = payload(
        content="建议结论：系数只能全为零。", expected_version=1, reason="补全缺失条件", **changes
    )
    response = client.post(path + "/proposals", json=data)
    assert response.status_code == 201
    proposal = response.json()
    return point, proposal, path, path + f"/proposals/{proposal['id']}/accept"


def test_model_revision_is_applied_and_opinion_and_execution_are_persisted(
    client, course, db_engine, monkeypatch
):
    point, _proposal, path, accept = suggestion(client, course)

    def review(current, proposed, reason, sources, images, limited):
        assert current["content"] == point["content"]
        assert reason == "补全缺失条件"
        return make_response(
            proposed, verdict="revise", content="模型修订后的定义：零线性组合的系数只能全为零。"
        )

    monkeypatch.setattr(proposal_processing, "review_proposal", review)
    result = client.post(accept, json={"expected_version": 1})
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["version"] == 2
    assert saved["content"].startswith("模型修订后的定义")
    report = saved["processing"]
    assert report["opinion"] == "建议补全了判断条件，可以采纳。"
    assert report["applied"] is True
    assert report["applied_version"] == 2
    assert report["model"] == "qwen3.8-flash"
    assert any(tool["name"] == "save_knowledge_revision" for tool in report["tools"])
    stored = client.get(path + "/proposals").json()[0]
    assert stored["llm_review"] == report
    assert stored["status"] == "accepted"
    assert not stored["processing"]
    assert search(client, course, "旧结论") == []
    assert search(client, course, "模型修订后的定义")
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(KnowledgeRevision.id))) == 2
        assert all(
            row.version == 2 and row.embedding is None for row in db.scalars(select(KnowledgeChunk))
        )
    assert client.post(accept, json={"expected_version": 2}).status_code == 409


@pytest.mark.parametrize("verdict, status", [("reject", "rejected"), ("needs_evidence", "pending")])
def test_rejection_or_insufficient_evidence_never_updates_knowledge(
    client, course, db_engine, monkeypatch, verdict, status
):
    point, _proposal, path, accept = suggestion(client, course)
    monkeypatch.setattr(
        proposal_processing,
        "review_proposal",
        lambda current, proposed, *args: make_response(
            proposed,
            verdict=verdict,
            basis="insufficient",
            opinion="目前不能支持这项修改。",
            title="",
            summary="",
            content="",
            changes=[],
        ),
    )
    response = client.post(accept, json={"expected_version": 1})
    assert response.status_code == 200
    assert not response.json()["processing"]["applied"]
    assert response.json()["processing"]["outcome"] == (
        "rejected" if verdict == "reject" else verdict
    )
    assert client.get(path).json()["content"] == point["content"]
    assert client.get(path + "/proposals").json()[0]["status"] == status
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(KnowledgeRevision.id))) == 1


def test_model_failure_preserves_knowledge_and_allows_retry_without_leaking_details(
    client, course, monkeypatch
):
    _point, _proposal, path, accept = suggestion(client, course)

    def fail(*args):
        raise ModelAPIError("private-key-and-provider-error")

    monkeypatch.setattr(proposal_processing, "review_proposal", fail)
    response = client.post(accept, json={"expected_version": 1})
    assert response.status_code == 502
    assert "private-key" not in response.text
    result = client.get(path + "/proposals").json()[0]
    assert result["status"] == "pending" and not result["processing"]
    assert result["llm_review"]["outcome"] == "error"
    assert client.get(path).json()["version"] == 1
    monkeypatch.setattr(proposal_processing, "review_proposal", approved_response)
    assert client.post(accept, json={"expected_version": 1}).json()["processing"]["applied"]


def test_knowledge_changed_during_model_call_is_not_overwritten(
    client, course, account, db_engine, monkeypatch
):
    point, _proposal, path, accept = suggestion(client, course)

    def concurrent_edit(current, proposed, *args):
        with Session(db_engine) as db:
            copy = find_knowledge(db, course["id"], point["id"])
            update_knowledge(
                db,
                copy,
                account["id"],
                KnowledgeUpdate(
                    **payload(content="并发请求的新版本", expected_version=1, reason="另一处编辑")
                ),
            )
        return make_response(proposed)

    monkeypatch.setattr(proposal_processing, "review_proposal", concurrent_edit)
    response = client.post(accept, json={"expected_version": 1})
    assert response.status_code == 200, response.text
    report = response.json()["processing"]
    assert report["outcome"] == "stale" and not report["applied"]
    assert report["opinion"]
    assert client.get(path).json()["content"] == "并发请求的新版本"
    assert client.get(path + "/proposals").json()[0]["status"] == "superseded"


def test_duplicate_accept_and_reject_are_blocked_while_model_is_running(
    client, course, monkeypatch
):
    _point, proposal, path, accept = suggestion(client, course)
    calls = []

    def running(current, proposed, *args):
        calls.append(True)
        assert client.post(accept, json={"expected_version": 1}).status_code == 409
        assert (
            client.post(
                path + f"/proposals/{proposal['id']}/reject", json={"expected_version": 1}
            ).status_code
            == 409
        )
        return make_response(proposed)

    monkeypatch.setattr(proposal_processing, "review_proposal", running)
    assert client.post(accept, json={"expected_version": 1}).status_code == 200
    assert len(calls) == 1


def test_failed_write_rolls_back_revision_index_and_proposal_acceptance(
    client, course, db_engine, monkeypatch
):
    point, _proposal, path, accept = suggestion(client, course)
    monkeypatch.setattr(proposal_processing, "review_proposal", approved_response)

    def fail(*args):
        raise RuntimeError("Synthetic write failure")

    monkeypatch.setattr(proposal_processing, "save_revision", fail)
    response = client.post(accept, json={"expected_version": 1})
    assert response.status_code == 500
    assert client.get(path).json()["content"] == point["content"]
    result = client.get(path + "/proposals").json()[0]
    assert result["status"] == "pending" and not result["processing"]
    assert result["llm_review"]["outcome"] == "error" and not result["llm_review"]["applied"]
    assert search(client, course, "旧结论")
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(KnowledgeRevision.id))) == 1


def test_model_receives_verified_course_page_image_and_reports_source_tool(
    client, course, pdf_bytes, monkeypatch
):
    document = upload(client, course, pdf_bytes)
    point = create(client, course, sources=[{"document_id": document["id"], "page_number": 1}])
    path = base(course) + "/" + point["id"]
    proposal = client.post(
        path + "/proposals",
        json=payload(
            content="课件中的定义",
            expected_version=1,
            reason="依照课件修正",
            sources=[{"document_id": document["id"], "page_number": 1}],
        ),
    ).json()

    def review(current, proposed, reason, sources, images, limited):
        assert len(sources) == len(images) == 1
        assert sources[0]["document_id"] == document["id"]
        assert "Chapter 1" in sources[0]["text"]
        assert images[0].startswith(b"\x89PNG")
        return make_response(
            proposed,
            basis="source",
            evidence=[{"source_key": "source-1", "observation": "该页显示线性代数章节标题。"}],
        )

    monkeypatch.setattr(proposal_processing, "review_proposal", review)
    response = client.post(
        path + f"/proposals/{proposal['id']}/accept", json={"expected_version": 1}
    )
    assert response.status_code == 200
    report = response.json()["processing"]
    assert report["tools"][0] == {
        "name": "read_source_page",
        "source_key": "source-1",
        "status": "read",
    }
    assert "text" not in report["sources"][0]


def test_cross_user_cannot_trigger_model_processing(client, course, monkeypatch):
    _point, _proposal, _path, accept = suggestion(client, course)
    monkeypatch.setattr(
        proposal_processing, "review_proposal", lambda *args: pytest.fail("Unauthorized model call")
    )
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={"email": "review-other@example.com", "name": "Other", "password": "another-password"},
    )
    assert client.post(accept, json={"expected_version": 1}).status_code == 404


def test_unsupported_source_from_model_is_rejected_before_any_write(monkeypatch):
    proposed = payload()
    review = make_response(
        proposed,
        basis="source",
        evidence=[{"source_key": "invented-source", "observation": "Invented citation"}],
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "model": "qwen3.8-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": review.parsed.model_dump_json(),
                        },
                    }
                ],
            },
        )
    )
    settings = Settings(
        _env_file=None,
        llm_api_key=SecretStr("sk-test-credential"),
        llm_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        llm_model="qwen3.8-flash",
    )
    monkeypatch.setattr(
        proposal_review, "LLMClient", lambda: LLMClient(settings, transport=transport)
    )
    with pytest.raises(ModelAPIError, match="unavailable source"):
        proposal_review.review_proposal(proposed, proposed, "Check", [], [], False)


def test_deleting_pending_proposal_removes_record_without_changing_knowledge(
    client, course, db_engine
):
    point, proposal, path, _accept = suggestion(client, course)
    endpoint = path + f"/proposals/{proposal['id']}"
    assert client.delete(endpoint).status_code == 204
    assert client.get(path + "/proposals").json() == []
    assert client.get(base(course) + "/stats").json()["pending_proposals"] == 0
    assert client.get(path).json()["content"] == point["content"]
    assert client.delete(endpoint).status_code == 404
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(KnowledgeRevision.id))) == 1


def test_deleting_processed_proposal_keeps_revision_and_retrieval(
    client, course, db_engine, monkeypatch
):
    _point, proposal, path, accept = suggestion(client, course)
    monkeypatch.setattr(proposal_processing, "review_proposal", approved_response)
    result = client.post(accept, json={"expected_version": 1}).json()
    assert result["processing"]["applied"]
    assert client.delete(path + f"/proposals/{proposal['id']}").status_code == 204
    assert client.get(path).json()["content"] == result["content"]
    assert client.get(path).json()["version"] == 2
    assert search(client, course, "建议结论")
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(KnowledgeRevision.id))) == 2
        assert (
            db.scalar(select(KnowledgeRevision.proposal_id).where(KnowledgeRevision.version == 2))
            == proposal["id"]
        )


def test_proposal_delete_is_owner_scoped_and_blocks_running_model(client, course, monkeypatch):
    _point, proposal, path, accept = suggestion(client, course)

    def running(current, proposed, *args):
        assert client.delete(path + f"/proposals/{proposal['id']}").status_code == 409
        return make_response(proposed)

    monkeypatch.setattr(proposal_processing, "review_proposal", running)
    assert client.post(accept, json={"expected_version": 1}).status_code == 200
    other_course = client.post("/api/courses", json={"name": "Other course"}).json()
    assert (
        client.delete(
            base(other_course) + path[len(base(course)) :] + f"/proposals/{proposal['id']}"
        ).status_code
        == 404
    )
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={"email": "delete-other@example.com", "name": "Other", "password": "another-password"},
    )
    assert client.delete(path + f"/proposals/{proposal['id']}").status_code == 404
