from unittest.mock import patch

import pytest
from app.models import (
    DocumentPage,
    KnowledgeChunk,
    KnowledgePoint,
    KnowledgeProposal,
    KnowledgeRevision,
    KnowledgeSource,
    SourceFragment,
)
from app.schemas.knowledge import KnowledgeUpdate
from app.services.knowledge import find_knowledge, update_knowledge
from app.services.knowledge_index import store_embeddings
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError


def base(course):
    return f"/api/courses/{course['id']}/knowledge"


def payload(**changes):
    return {
        "title": "线性无关",
        "summary": "判断向量组的关系",
        "content": "旧结论：非零向量一定线性无关。",
        **changes,
    }


def create(client, course, **changes):
    response = client.post(base(course), json=payload(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, course, pdf_bytes):
    response = client.post(
        f"/api/courses/{course['id']}/documents",
        files={"file": ("lecture.pdf", pdf_bytes, "application/pdf")},
    )
    assert response.status_code == 201
    return response.json()


def search(client, course, query):
    response = client.post(base(course) + "/search", json={"query": query})
    assert response.status_code == 200, response.text
    return response.json()


def test_sources_are_verified_and_pages_are_cached(client, course, pdf_bytes, db_engine):
    document = upload(client, course, pdf_bytes)
    source = {"document_id": document["id"], "page_number": 2, "quote": "Vectors and matrices"}
    point = create(client, course, sources=[source])
    assert point["version"] == 1
    reference = point["sources"][0]
    assert reference["page_number"] == 2
    assert reference["quote"] == source["quote"]
    response = client.post(f"/api/documents/{document['id']}/pages/2/extract")
    assert response.status_code == 200
    assert source["quote"] in response.json()["text"]
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(DocumentPage.id))) == 1
        fragment = db.get(SourceFragment, reference["fragment_id"])
        page = db.get(DocumentPage, fragment.page_id)
        assert page.text[fragment.char_start : fragment.char_end] == reference["quote"]
        assert db.scalar(select(func.count(KnowledgeChunk.id))) > 0
    assert client.get(f"/api/documents/{document['id']}/file").content == pdf_bytes
    assert client.get(base(course) + "/stats").json()["active"] == 1


def test_edits_replace_old_retrieval_content_and_vectors(client, course, db_engine):
    point = create(client, course)
    with Session(db_engine) as db:
        assert store_embeddings(db, point["id"], 1, [[0.1, 0.2]], "test-model")
        db.commit()
    response = client.patch(
        base(course) + f"/{point['id']}",
        json=payload(
            expected_version=1,
            content="新结论：只有零线性组合对应的系数全为零时才线性无关。",
            reason="原结论缺少条件",
        ),
    )
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert search(client, course, "旧结论") == []
    assert search(client, course, "新结论")[0]["version"] == 2
    history = client.get(base(course) + f"/{point['id']}/revisions").json()
    assert [item["version"] for item in history] == [2, 1]
    assert "旧结论" in history[1]["snapshot"]["content"]
    with Session(db_engine) as db:
        chunks = list(db.scalars(select(KnowledgeChunk)))
        assert all(
            chunk.version == 2 and chunk.embedding is None and chunk.embedding_status == "pending"
            for chunk in chunks
        )
        assert store_embeddings(db, point["id"], 1, [[0.9, 0.8]], "stale-model") is False


def test_stale_edit_and_invalid_embedding_batch_do_not_overwrite(client, course, db_engine):
    point = create(client, course)
    path = base(course) + f"/{point['id']}"
    assert (
        client.patch(path, json=payload(expected_version=2, reason="过期版本")).status_code == 409
    )
    assert client.get(path).json()["version"] == 1
    with Session(db_engine) as db:
        with pytest.raises(ValueError):
            store_embeddings(db, point["id"], 1, [[float("nan")]], "bad-model")
        assert db.scalar(select(KnowledgeChunk)).embedding is None


def test_proposal_requires_confirmation_and_cannot_be_applied_twice(client, course, monkeypatch):
    from app.services import proposal_processing
    from test_proposal_review import approved_response

    monkeypatch.setattr(proposal_processing, "review_proposal", approved_response)
    point = create(client, course)
    path = base(course) + f"/{point['id']}"
    proposal = client.post(
        path + "/proposals",
        json=payload(
            content="已确认的纠正：需要检查线性组合系数。",
            expected_version=1,
            reason="核对课件后修正",
        ),
    )
    assert proposal.status_code == 201, proposal.text
    suggestion = proposal.json()
    assert client.get(path).json()["content"] == point["content"]
    assert search(client, course, "已确认的纠正") == []
    assert client.get(base(course) + "/stats").json()["pending_proposals"] == 1
    accepted = client.post(
        path + f"/proposals/{suggestion['id']}/accept", json={"expected_version": 1}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["version"] == 2
    assert search(client, course, "已确认的纠正")
    assert search(client, course, "旧结论") == []
    assert client.get(path + "/proposals").json()[0]["status"] == "accepted"
    assert client.get(path + "/revisions").json()[0]["operation"] == "correction"
    assert (
        client.post(
            path + f"/proposals/{suggestion['id']}/accept", json={"expected_version": 2}
        ).status_code
        == 409
    )


def test_rejected_and_superseded_proposals_do_not_change_knowledge(client, course):
    point = create(client, course)
    path = base(course) + f"/{point['id']}"
    first = client.post(
        path + "/proposals", json=payload(expected_version=1, reason="待核对")
    ).json()
    assert (
        client.post(
            path + f"/proposals/{first['id']}/reject", json={"expected_version": 1}
        ).status_code
        == 200
    )
    assert client.get(path).json()["version"] == 1
    second = client.post(
        path + "/proposals", json=payload(expected_version=1, reason="另一条建议")
    ).json()
    assert (
        client.patch(path, json=payload(expected_version=1, reason="手动修订")).status_code == 200
    )
    states = {item["id"]: item["status"] for item in client.get(path + "/proposals").json()}
    assert states[first["id"]] == "rejected"
    assert states[second["id"]] == "superseded"
    assert (
        client.post(
            path + f"/proposals/{second['id']}/accept", json={"expected_version": 2}
        ).status_code
        == 409
    )


def test_archive_and_restore_keep_history_and_hide_stale_chunks(client, course, db_engine):
    point = create(client, course)
    path = base(course) + f"/{point['id']}"
    first_revision = client.get(path + "/revisions").json()[0]
    assert client.delete(path, params={"expected_version": 1}).status_code == 204
    assert client.get(base(course)).json() == []
    assert client.get(base(course), params={"status": "archived"}).json()[0]["id"] == point["id"]
    assert search(client, course, "旧结论") == []
    with Session(db_engine) as db:
        assert db.scalar(select(func.count(KnowledgeChunk.id))) == 0
        db.add(
            KnowledgeChunk(
                course_id=course["id"],
                knowledge_id=point["id"],
                version=1,
                position=0,
                text="旧结论",
                content_hash="old",
                embedding_status="pending",
            )
        )
        db.commit()
    assert search(client, course, "旧结论") == []
    restored = client.post(
        path + "/restore",
        json={
            "revision_id": first_revision["id"],
            "expected_version": 2,
            "reason": "恢复原笔记",
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["version"] == 3
    assert restored.json()["status"] == "active"
    assert search(client, course, "旧结论")[0]["version"] == 3


def test_cross_course_and_cross_user_access_is_blocked(client, course, pdf_bytes):
    document = upload(client, course, pdf_bytes)
    point = create(client, course, sources=[{"document_id": document["id"], "page_number": 1}])
    other = client.post("/api/courses", json={"name": "另一门课"}).json()
    assert (
        client.post(
            base(other), json=payload(sources=[{"document_id": document["id"], "page_number": 1}])
        ).status_code
        == 422
    )
    assert search(client, other, "旧结论") == []
    for suffix in ["", "/revisions", "/proposals"]:
        assert client.get(base(other) + f"/{point['id']}" + suffix).status_code == 404
    assert (
        client.patch(
            f"/api/courses/{other['id']}/source-fragments/{point['sources'][0]['fragment_id']}",
            json={"excluded": True, "reason": "跨课引用"},
        ).status_code
        == 404
    )
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/register",
        json={"email": "outsider@example.com", "name": "其他用户", "password": "other-password"},
    )
    for suffix in [
        "",
        "/stats",
        f"/{point['id']}",
        f"/{point['id']}/revisions",
        f"/{point['id']}/proposals",
    ]:
        assert client.get(base(course) + suffix).status_code == 404
    assert client.post(base(course) + "/search", json={"query": "旧结论"}).status_code == 404
    assert client.post(f"/api/documents/{document['id']}/pages/1/extract").status_code == 404
    assert client.delete(base(course) + f"/{point['id']}?expected_version=1").status_code == 404


def test_deleted_document_preserves_citations_and_revision_restore(client, course, pdf_bytes):
    document = upload(client, course, pdf_bytes)
    point = create(
        client,
        course,
        sources=[
            {"document_id": document["id"], "page_number": 2, "quote": "Vectors and matrices"}
        ],
    )
    path = base(course) + f"/{point['id']}"
    original = client.get(path + "/revisions").json()[0]
    assert client.delete(f"/api/documents/{document['id']}").status_code == 204
    point = client.get(path).json()
    source = point["sources"][0]
    assert source["document_id"] is None
    assert source["fragment_id"] is None
    assert source["quote"] == "Vectors and matrices"
    edited = client.patch(
        path,
        json=payload(
            expected_version=1,
            reason="补充笔记",
            sources=[
                {
                    "document_id": None,
                    "source_id": source["id"],
                    "page_number": 2,
                }
            ],
        ),
    )
    assert edited.status_code == 200, edited.text
    restored = client.post(
        path + "/restore",
        json={
            "revision_id": original["id"],
            "expected_version": 2,
            "reason": "恢复历史引用",
        },
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["sources"][0]["document_id"] is None
    assert restored.json()["sources"][0]["quote"] == "Vectors and matrices"


@pytest.mark.parametrize("page_number,quote", [(3, ""), (1, "课件中不存在的原文")])
def test_invalid_citations_roll_back_all_records(
    client, course, pdf_bytes, db_engine, page_number, quote
):
    document = upload(client, course, pdf_bytes)
    response = client.post(
        base(course),
        json=payload(
            sources=[
                {
                    "document_id": document["id"],
                    "page_number": page_number,
                    "quote": quote,
                }
            ]
        ),
    )
    assert response.status_code == 422
    with Session(db_engine) as db:
        for model in [
            KnowledgePoint,
            KnowledgeChunk,
            KnowledgeRevision,
            KnowledgeSource,
            DocumentPage,
        ]:
            assert db.scalar(select(func.count(model.id))) == 0


def test_revision_and_index_roll_back_together_on_write_failure(client, course):
    point = create(client, course)
    path = base(course) + f"/{point['id']}"
    with (
        patch("sqlalchemy.orm.Session.commit", side_effect=RuntimeError("write failed")),
        pytest.raises(RuntimeError, match="write failed"),
    ):
        client.patch(
            path, json=payload(expected_version=1, content="未提交内容", reason="事务测试")
        )
    assert client.get(path).json()["version"] == 1
    assert search(client, course, "旧结论")
    assert search(client, course, "未提交内容") == []
    assert len(client.get(path + "/revisions").json()) == 1


def test_concurrent_sessions_cannot_silently_overwrite(client, course, account, db_engine):
    point = create(client, course)
    with (
        Session(db_engine, expire_on_commit=False) as first,
        Session(db_engine, expire_on_commit=False) as second,
    ):
        first_copy = find_knowledge(first, course["id"], point["id"])
        second_copy = find_knowledge(second, course["id"], point["id"])
        update_knowledge(
            first,
            first_copy,
            account["id"],
            KnowledgeUpdate(
                **payload(
                    expected_version=1,
                    content="第一个请求的修订",
                    reason="第一处修改",
                )
            ),
        )
        with pytest.raises(StaleDataError):
            update_knowledge(
                second,
                second_copy,
                account["id"],
                KnowledgeUpdate(
                    **payload(
                        expected_version=1,
                        content="第二个请求的修订",
                        reason="并发修改",
                    )
                ),
            )
    assert search(client, course, "第一个请求")
    assert search(client, course, "第二个请求") == []


def test_exclusions_and_course_delete_cleanup(client, course, pdf_bytes, db_engine):
    document = upload(client, course, pdf_bytes)
    point = create(client, course, sources=[{"document_id": document["id"], "page_number": 1}])
    fragment_id = point["sources"][0]["fragment_id"]
    response = client.patch(
        f"/api/courses/{course['id']}/source-fragments/{fragment_id}",
        json={"excluded": True, "reason": "原文中有已知错误"},
    )
    assert response.status_code == 200
    assert response.json()["excluded"] is True
    assert client.delete(f"/api/courses/{course['id']}").status_code == 204
    with Session(db_engine) as db:
        for model in [
            DocumentPage,
            SourceFragment,
            KnowledgePoint,
            KnowledgeSource,
            KnowledgeRevision,
            KnowledgeProposal,
            KnowledgeChunk,
        ]:
            assert db.scalar(select(func.count(model.id))) == 0


def test_queries_treat_wildcards_as_text_and_reject_empty_input(client, course):
    create(client, course)
    assert search(client, course, "%") == []
    assert client.get(base(course), params={"q": "%"}).json() == []
    assert client.post(base(course) + "/search", json={"query": "   "}).status_code == 422


def test_keyword_across_chunk_boundary_can_be_found(client, course):
    keyword = "边界" * 100
    point = create(client, course, content="前" * 1001 + keyword + "后" * 2000)
    assert search(client, course, keyword)[0]["knowledge_id"] == point["id"]


def test_postgresql_vector_roundtrip_and_cosine_distance(client, course, db_engine):
    if db_engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL integration database is not configured")
    point = create(client, course)
    with Session(db_engine) as db:
        assert store_embeddings(db, point["id"], 1, [[1.0, 0.0, 0.0]], "integration-test")
        db.commit()
        distance = db.scalar(select(KnowledgeChunk.embedding.cosine_distance([1.0, 0.0, 0.0])))
        assert distance == pytest.approx(0.0)
        assert (
            db.scalar(text("SELECT pg_typeof(embedding)::text FROM knowledge_chunks LIMIT 1"))
            == "vector"
        )
