from app.llm.cache import LlmCache, make_key


def test_make_key_is_stable_and_sensitive():
    k1 = make_key("gemini|groq", "sys", "user", 0.2, 100)
    k2 = make_key("gemini|groq", "sys", "user", 0.2, 100)
    k3 = make_key("gemini|groq", "sys", "user2", 0.2, 100)
    assert k1 == k2
    assert k1 != k3


def test_cache_hit_miss_and_stats():
    cache = LlmCache(enabled=True, ttl_seconds=100)
    assert cache.get("a") is None
    cache.set("a", "value")
    assert cache.get("a") == "value"
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1


def test_disabled_cache_returns_none():
    cache = LlmCache(enabled=False)
    cache.set("a", "value")
    assert cache.get("a") is None


def test_ttl_expiry():
    import time

    cache = LlmCache(enabled=True, ttl_seconds=1)
    cache.set("a", "value")
    # Backdate the entry well beyond the TTL to force expiry deterministically.
    cache._mem["a"] = (time.time() - 100, "value")
    assert cache.get("a") is None


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "cache.sqlite"
    c1 = LlmCache(enabled=True, ttl_seconds=100, persist_path=path)
    c1.set("k", "persisted")
    # New instance reading the same file should find the value.
    c2 = LlmCache(enabled=True, ttl_seconds=100, persist_path=path)
    assert c2.get("k") == "persisted"
