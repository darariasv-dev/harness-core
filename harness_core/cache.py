"""A persistent, composite-hash result cache: the key is a stable hash over an ORDERED set of
named hash components (e.g. content identity, a set of input facts, a policy version) --
never a single opaque blob -- so a caller can invalidate exactly the entries a single
component's change should affect, and no others. Owns its own SQLite schema; never assumes
what the cached value represents beyond "some JSON-serializable dict."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path("cache.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    cache_key TEXT PRIMARY KEY,
    components_json TEXT NOT NULL,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def get_connection(path: Path = DEFAULT_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def compute_cache_key(components: dict) -> str:
    """`components` is an ordered {name: value} mapping (Python dicts preserve insertion
    order) -- the caller decides what identifies a cacheable unit of work and under what
    names. Order matters for reproducibility: always pass the same component order for the
    same logical key.

    Hashed as a JSON-encoded list of [name, value] pairs, never a delimiter-joined string --
    a plain `":".join(f"{k}={v}")` is not collision-safe: {"a": "x:b=y"} and {"a": "x", "b":
    "y"} join to the identical string and would silently share a cache entry. JSON's own
    escaping makes every distinct (names, values) pair produce a distinct encoding regardless
    of what characters a value contains."""
    encoded = json.dumps(list(components.items()), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def get_cached(conn: sqlite3.Connection, cache_key: str) -> "dict | None":
    row = conn.execute("SELECT value_json FROM cache_entries WHERE cache_key = ?", (cache_key,)).fetchone()
    if row is None:
        return None
    return json.loads(row["value_json"])


def save_cached(conn: sqlite3.Connection, cache_key: str, components: dict, value: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO cache_entries (cache_key, components_json, value_json, created_at) VALUES (?, ?, ?, ?)",
        (cache_key, json.dumps(components), json.dumps(value), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
