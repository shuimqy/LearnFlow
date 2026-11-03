import pytest
from app.core.config import Settings
from app.services import query_embeddings as cache
from app.services.model_api import ModelAPIError
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def reset_cache():
    cache.clear_query_cache()
    yield
    cache.clear_query_cache()


def config(**changes):
    return Settings(
        _env_file=None,
        **{
            "embedding_api_key": SecretStr("sk-cache-test"),
            "embedding_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "embedding_model": "embedding-test",
            "embedding_dimensions": 2,
            **changes,
        },
    )


def test_identical_query_reuses_vector_and_returns_copy():
    calls = []

    def embed(text):
        return calls.append(text) or [1.0, 0.0]

    first = cache.query_embedding(config(), "u1", "c1", "测试问题", embed)
    first[0] = 999
    assert cache.query_embedding(config(), "u1", "c1", "测试问题", embed) == [1.0, 0.0]
    assert calls == ["测试问题"]
    assert "测试问题" not in repr(cache._entries)
    assert "sk-cache-test" not in repr(cache._entries)


@pytest.mark.parametrize(
    "changes",
    [
        {"embedding_model": "other-model"},
        {"embedding_dimensions": 3},
        {"embedding_revision": "v2"},
        {"embedding_send_dimensions": False},
        {"embedding_provider": "openai_compatible"},
        {"embedding_base_url": "https://other.example/v1"},
        {"embedding_api_key": SecretStr("sk-new-cache-key")},
    ],
)
def test_model_configuration_changes_never_mix_vectors(changes):
    calls = []

    def embed(text):
        return calls.append(text) or [1.0, 0.0]

    cache.query_embedding(config(), "u1", "c1", "q", embed)
    cache.query_embedding(config(**changes), "u1", "c1", "q", embed)
    assert len(calls) == 2


def test_query_scope_ttl_and_deletion(monkeypatch):
    timer = [100.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: timer[0])
    calls = []

    def embed(text):
        return calls.append(text) or [1.0, 0.0]

    for user, course in (("u1", "c1"), ("u2", "c1"), ("u1", "c2")):
        cache.query_embedding(config(), user, course, "q", embed)
    assert len(calls) == 3
    cache.clear_query_cache("u1", "c1")
    assert len(cache._entries) == 2
    cache.query_embedding(config(), "u1", "c1", "q", embed)
    timer[0] += cache.TTL_SECONDS + 1
    cache.query_embedding(config(), "u1", "c1", "q", embed)
    assert len(calls) == 5 and len(cache._entries) == 1


def test_failures_are_not_cached_and_inflight_deletion_cannot_repopulate():
    def fail(text):
        raise ModelAPIError("failed")

    with pytest.raises(ModelAPIError):
        cache.query_embedding(config(), "u1", "c1", "q", fail)
    assert not cache._entries

    def delete(text):
        cache.clear_query_cache("u1", "c1")
        return [1.0, 0.0]

    assert cache.query_embedding(config(), "u1", "c1", "q", delete) == [1.0, 0.0]
    assert not cache._entries


def test_cache_has_a_bounded_size(monkeypatch):
    monkeypatch.setattr(cache, "MAX_ENTRIES", 2)
    for query in ("a", "b", "c"):
        cache.query_embedding(config(), "u1", "c1", query, lambda text: [1.0, 0.0])
    assert len(cache._entries) == 2
