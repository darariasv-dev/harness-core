from harness_core import ledger


def make_conn(tmp_path):
    return ledger.get_connection(tmp_path / "ledger.db")


def test_record_call_started_and_finished(tmp_path):
    conn = make_conn(tmp_path)
    call_id = ledger.record_call_started(conn, task_id=None, purpose="test", model="m1", prompt_chars=10)
    ledger.record_call_finished(conn, call_id, success=True, response_chars=5, usage={
        "measured": True, "input_tokens": 1, "output_tokens": 2,
        "cache_creation_input_tokens": 3, "cache_read_input_tokens": 4,
        "total_cost_usd": 0.01, "duration_api_ms": 100, "thinking_tokens": 0,
    })
    row = conn.execute("SELECT * FROM headless_calls WHERE id = ?", (call_id,)).fetchone()
    assert row["success"] == 1
    assert row["usage_source"] == "measured"
    assert row["input_tokens"] == 1


def test_record_call_finished_without_usage_is_estimated(tmp_path):
    conn = make_conn(tmp_path)
    call_id = ledger.record_call_started(conn, task_id=None, purpose="test")
    ledger.record_call_finished(conn, call_id, success=False, error="boom")
    row = conn.execute("SELECT * FROM headless_calls WHERE id = ?", (call_id,)).fetchone()
    assert row["usage_source"] == "estimated"
    assert row["input_tokens"] is None


def test_calls_today_count(tmp_path):
    conn = make_conn(tmp_path)
    ledger.record_call_started(conn, task_id=None, purpose="test")
    assert ledger.calls_today_count(conn) == 1


def test_usage_summary_groups_by_purpose(tmp_path):
    conn = make_conn(tmp_path)
    call_id = ledger.record_call_started(conn, task_id=None, purpose="test", prompt_chars=100)
    ledger.record_call_finished(conn, call_id, success=True, response_chars=50, usage={
        "measured": True, "input_tokens": 10, "output_tokens": 20,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "total_cost_usd": 0.02, "duration_api_ms": 500, "thinking_tokens": 5,
    })
    summary = ledger.usage_summary(conn)
    assert len(summary) == 1
    assert summary[0]["purpose"] == "test"
    assert summary[0]["measured_input_tokens"] == 10
    assert summary[0]["measured_thinking_tokens"] == 5


def test_persists_across_connections(tmp_path):
    path = tmp_path / "ledger.db"
    conn1 = ledger.get_connection(path)
    ledger.record_call_started(conn1, task_id=None, purpose="test")
    conn1.close()
    conn2 = ledger.get_connection(path)
    assert ledger.calls_today_count(conn2) == 1


def test_get_connection_adds_num_turns_to_an_older_ledger(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE headless_calls (id TEXT PRIMARY KEY, task_id TEXT, purpose TEXT NOT NULL, success INTEGER, "
                "error TEXT, started_at TEXT NOT NULL, finished_at TEXT, model TEXT, prompt_chars INTEGER, "
                "response_chars INTEGER, input_tokens INTEGER, output_tokens INTEGER, cache_creation_input_tokens INTEGER, "
                "cache_read_input_tokens INTEGER, total_cost_usd REAL, duration_api_ms INTEGER, usage_source TEXT, "
                "thinking_tokens INTEGER)")
    old.commit(); old.close()
    conn = ledger.get_connection(path)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(headless_calls)")}
    assert {"provider", "num_turns"} <= cols
