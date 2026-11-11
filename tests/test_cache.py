from harness_core import cache


def make_conn(tmp_path):
    return cache.get_connection(tmp_path / "cache.db")


def test_compute_cache_key_deterministic():
    k1 = cache.compute_cache_key({"a": "1", "b": "2"})
    k2 = cache.compute_cache_key({"a": "1", "b": "2"})
    assert k1 == k2


def test_compute_cache_key_changes_with_any_component():
    base = cache.compute_cache_key({"a": "1", "b": "2"})
    assert cache.compute_cache_key({"a": "9", "b": "2"}) != base
    assert cache.compute_cache_key({"a": "1", "b": "9"}) != base


def test_compute_cache_key_not_confused_by_delimiter_characters_in_values():
    """A naive ":".join(f"{k}={v}") joiner would make {"a": "x:b=y"} collide with
    {"a": "x", "b": "y"} -- both join to the same string. Real component values (raw prompt
    text, file paths, freeform task identifiers) can contain ':' or '=' at any time, so this
    must never collide."""
    one_component_with_delimiters = cache.compute_cache_key({"a": "x:b=y"})
    two_plain_components = cache.compute_cache_key({"a": "x", "b": "y"})
    assert one_component_with_delimiters != two_plain_components


def test_compute_cache_key_distinguishes_key_count_from_value_content():
    """A single component whose value happens to look like another component's k=v pair must
    still hash differently from actually having that second component."""
    assert cache.compute_cache_key({"only": "a=1:b=2"}) != cache.compute_cache_key({"only": "a=1", "b": "2"})


def test_get_cached_returns_none_when_absent(tmp_path):
    conn = make_conn(tmp_path)
    assert cache.get_cached(conn, "nope") is None


def test_save_and_get_round_trip(tmp_path):
    conn = make_conn(tmp_path)
    key = cache.compute_cache_key({"a": "1"})
    cache.save_cached(conn, key, {"a": "1"}, {"result": 42})
    assert cache.get_cached(conn, key) == {"result": 42}


def test_save_overwrites_same_key(tmp_path):
    conn = make_conn(tmp_path)
    key = cache.compute_cache_key({"a": "1"})
    cache.save_cached(conn, key, {"a": "1"}, {"result": 1})
    cache.save_cached(conn, key, {"a": "1"}, {"result": 2})
    assert cache.get_cached(conn, key) == {"result": 2}


def test_persists_across_connections(tmp_path):
    path = tmp_path / "cache.db"
    conn1 = cache.get_connection(path)
    key = cache.compute_cache_key({"a": "1"})
    cache.save_cached(conn1, key, {"a": "1"}, {"result": 42})
    conn1.close()
    conn2 = cache.get_connection(path)
    assert cache.get_cached(conn2, key) == {"result": 42}
