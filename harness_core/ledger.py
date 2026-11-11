"""A model-call usage ledger: a call count and outcome log, never a dollar or
quota-percentage figure presented as settled (a subscription plan generally has no
programmatic quota check) -- see harness_core.router's own docstring for the same point
applied to routing.

Records THREE separate, never-summed-together kinds of usage signal per call:

1. **Raw text volume** (`prompt_chars`/`response_chars`) -- always available, a rough size
   proxy, never called "tokens."
2. **Measured, provider-reported usage** (`input_tokens`/`output_tokens`/
   `cache_read_tokens`/`cache_creation_tokens`/`total_cost_usd`/`duration_api_ms`/
   `thinking_tokens`) -- parsed from the model call's own usage envelope when present. This
   is the provider's own accounting, not a derived estimate. `thinking_tokens` is a SUBSET
   already counted inside `output_tokens`, stored for separate reporting only, never
   subtracted from or added to it.
3. **A chars/4 estimate**, computed on demand in `usage_summary`, used only when measured
   usage wasn't available for a row.

`usage_source` on each row is 'measured' or 'estimated' -- summaries keep the two separate so
a report never silently blends a real provider number with a rough guess. Owns its own
SQLite schema (via `get_connection`) rather than assuming a caller's migration system --
consuming code that already has its own `headless_calls`-shaped table can keep using it
directly and only needs this module's pure functions (`record_call_started`, etc.) with that
existing connection.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

CHARS_PER_TOKEN_ESTIMATE = 4
USAGE_SOURCE_MEASURED = "measured"
USAGE_SOURCE_ESTIMATED = "estimated"

DEFAULT_PATH = Path("ledger.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS headless_calls (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    purpose TEXT NOT NULL,
    success INTEGER,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    model TEXT,
    prompt_chars INTEGER,
    response_chars INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_creation_input_tokens INTEGER,
    cache_read_input_tokens INTEGER,
    total_cost_usd REAL,
    duration_api_ms INTEGER,
    usage_source TEXT,
    thinking_tokens INTEGER,
    provider TEXT,
    num_turns INTEGER
);
"""

# Columns added after a ledger file may already exist on disk (CREATE TABLE IF NOT EXISTS
# never alters an existing table). `get_connection` adds any that are missing.
_LATER_COLUMNS = (("provider", "TEXT"), ("num_turns", "INTEGER"))


def _new_id() -> str:
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(path: Path = DEFAULT_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(headless_calls)").fetchall()}
    for column, column_type in _LATER_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE headless_calls ADD COLUMN {column} {column_type}")
    conn.commit()
    return conn


def record_call_started(
    conn: sqlite3.Connection,
    task_id: Optional[str],
    purpose: str,
    model: Optional[str] = None,
    prompt_chars: Optional[int] = None,
    provider: Optional[str] = None,
) -> str:
    call_id = _new_id()
    conn.execute(
        "INSERT INTO headless_calls (id, task_id, purpose, started_at, model, prompt_chars, provider) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (call_id, task_id, purpose, _now_iso(), model, prompt_chars, provider),
    )
    conn.commit()
    return call_id


def record_call_finished(
    conn: sqlite3.Connection,
    call_id: str,
    success: bool,
    error: Optional[str] = None,
    response_chars: Optional[int] = None,
    usage: Optional[dict] = None,
) -> None:
    """`usage`, when given, is {"measured": bool, "input_tokens", "output_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens", "total_cost_usd",
    "duration_api_ms", "thinking_tokens", "num_turns"}. `num_turns` is the provider's own count
    of model turns inside ONE call (the CLI's structured-output validation retries show up
    here as extra turns, each re-reading the whole context) -- NULL when not reported. When `usage["measured"]` is False (or `usage` is
    omitted), `usage_source` is recorded as 'estimated' and every provider-reported column
    stays NULL."""
    usage = usage or {}
    measured = bool(usage.get("measured"))
    conn.execute(
        """
        UPDATE headless_calls SET
            success = ?, error = ?, finished_at = ?, response_chars = ?,
            input_tokens = ?, output_tokens = ?, cache_creation_input_tokens = ?,
            cache_read_input_tokens = ?, total_cost_usd = ?, duration_api_ms = ?,
            usage_source = ?, thinking_tokens = ?, num_turns = ?
        WHERE id = ?
        """,
        (
            int(success), error, _now_iso(), response_chars,
            usage.get("input_tokens"), usage.get("output_tokens"),
            usage.get("cache_creation_input_tokens"), usage.get("cache_read_input_tokens"),
            usage.get("total_cost_usd"), usage.get("duration_api_ms"),
            USAGE_SOURCE_MEASURED if measured else USAGE_SOURCE_ESTIMATED,
            usage.get("thinking_tokens"), usage.get("num_turns"),
            call_id,
        ),
    )
    conn.commit()


def calls_today_count(conn: sqlite3.Connection) -> int:
    """Best-effort visibility only -- not an admission-control check."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM headless_calls WHERE date(started_at) = date('now')"
    ).fetchone()
    return row["c"]


def usage_summary(conn: sqlite3.Connection, since_days: Optional[int] = None) -> list[dict]:
    """Per-purpose usage summary. Never returns a dollar figure framed as an actual charge,
    or a percentage of any quota -- see this module's own docstring."""
    where = ""
    params: tuple = ()
    if since_days is not None:
        where = "WHERE started_at >= datetime('now', ?)"
        params = (f"-{since_days} days",)
    rows = conn.execute(
        f"""
        SELECT
            purpose,
            COUNT(*) AS call_count,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failure_count,
            COALESCE(SUM(prompt_chars), 0) AS total_prompt_chars,
            COALESCE(SUM(response_chars), 0) AS total_response_chars,
            SUM(CASE WHEN usage_source = 'measured' THEN 1 ELSE 0 END) AS measured_call_count,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN input_tokens END), 0) AS measured_input_tokens,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN output_tokens END), 0) AS measured_output_tokens,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN cache_read_input_tokens END), 0) AS measured_cache_read_tokens,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN cache_creation_input_tokens END), 0) AS measured_cache_creation_tokens,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN thinking_tokens END), 0) AS measured_thinking_tokens,
            MAX(num_turns) AS max_num_turns,
            SUM(CASE WHEN usage_source = 'measured' THEN total_cost_usd END) AS total_cost_usd
        FROM headless_calls
        {where}
        GROUP BY purpose
        ORDER BY call_count DESC
        """,
        params,
    ).fetchall()
    summary = []
    for row in rows:
        d = dict(row)
        d["est_prompt_tokens"] = d["total_prompt_chars"] // CHARS_PER_TOKEN_ESTIMATE
        d["est_response_tokens"] = d["total_response_chars"] // CHARS_PER_TOKEN_ESTIMATE
        summary.append(d)
    return summary


def usage_by_provider(conn: sqlite3.Connection, since_days: Optional[int] = None) -> list[dict]:
    """Per-(provider, model, purpose) usage. Rows written before the provider column existed
    report provider NULL -> shown as 'unknown'. Same measured/estimated separation as
    `usage_summary`; never a dollar figure framed as an actual charge."""
    where = ""
    params: tuple = ()
    if since_days is not None:
        where = "WHERE started_at >= datetime('now', ?)"
        params = (f"-{since_days} days",)
    rows = conn.execute(
        f"""
        SELECT
            COALESCE(provider, 'unknown') AS provider,
            COALESCE(model, 'unknown') AS model,
            purpose,
            COUNT(*) AS call_count,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failure_count,
            SUM(CASE WHEN usage_source = 'measured' THEN 1 ELSE 0 END) AS measured_call_count,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN input_tokens END), 0) AS measured_input_tokens,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN output_tokens END), 0) AS measured_output_tokens,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN cache_read_input_tokens END), 0) AS measured_cache_read_tokens,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN cache_creation_input_tokens END), 0) AS measured_cache_creation_tokens,
            COALESCE(SUM(CASE WHEN usage_source = 'measured' THEN duration_api_ms END), 0) AS measured_duration_ms,
            COALESCE(SUM(prompt_chars), 0) AS total_prompt_chars,
            COALESCE(SUM(response_chars), 0) AS total_response_chars
        FROM headless_calls
        {where}
        GROUP BY COALESCE(provider, 'unknown'), COALESCE(model, 'unknown'), purpose
        ORDER BY provider, model, call_count DESC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]
