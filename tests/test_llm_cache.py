from bball3x3.llm.cache import LLMCache, request_key


def test_request_key_is_stable_and_order_independent():
    a = request_key({"model": "m", "messages": [{"role": "user", "content": "q"}]})
    b = request_key({"messages": [{"role": "user", "content": "q"}], "model": "m"})
    assert a == b


def test_request_key_changes_with_content():
    a = request_key({"model": "m", "temperature": 0.7})
    b = request_key({"model": "m", "temperature": 0.0})
    assert a != b


def test_cache_miss_returns_none(tmp_path):
    cache = LLMCache(tmp_path / "c.sqlite")
    assert cache.get("missing") is None


def test_cache_round_trip_persists_across_instances(tmp_path):
    path = tmp_path / "sub" / "c.sqlite"
    LLMCache(path).put("k", {"text": "<RESPONSE/>", "prompt_tokens": 5})
    assert LLMCache(path).get("k") == {"text": "<RESPONSE/>", "prompt_tokens": 5}


def test_cache_put_overwrites(tmp_path):
    cache = LLMCache(tmp_path / "c.sqlite")
    cache.put("k", {"text": "old"})
    cache.put("k", {"text": "new"})
    assert cache.get("k") == {"text": "new"}
