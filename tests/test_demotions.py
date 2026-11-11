"""The per-provider demotion log and the strictly-above-15%-over-at-least-5 escalation rule."""
import pytest

from harness_core import demotions

P = "some_purpose"


@pytest.fixture(autouse=True)
def _log(tmp_path, monkeypatch):
    monkeypatch.setattr(demotions, "LOG_PATH", tmp_path / "demotions.jsonl")


def test_records_and_window_stats():
    demotions.record("local", "m", P, supported_claims=4, demoted=1)
    stats = demotions.window_stats("local")
    assert stats == {"provider": "local", "n": 1, "supported_claims": 4, "demoted": 1, "rate": 0.25}
    assert demotions.window_stats("other")["rate"] is None


def test_rate_above_015_over_at_least_5_records_escalates():
    for _ in range(5):
        demotions.record("local", "m", P, supported_claims=4, demoted=1)
    fired = demotions.should_escalate("local")
    assert fired["n"] == 5 and fired["rate"] == 0.25
    demotions.record_escalation("local", "m", P, rate=fired["rate"], n=fired["n"])
    assert demotions.escalation_events()[-1]["action"] == demotions.ACTION_ESCALATED


def test_exactly_015_or_too_few_records_does_not_escalate():
    for _ in range(5):
        demotions.record("local", "m", P, supported_claims=20, demoted=3)
    assert demotions.should_escalate("local") is None
    demotions.LOG_PATH.unlink()
    for _ in range(4):
        demotions.record("local", "m", P, supported_claims=1, demoted=1)
    assert demotions.should_escalate("local") is None


def test_window_is_the_last_20_records_per_provider():
    for _ in range(20):
        demotions.record("local", "m", P, 1, 1)
    for _ in range(20):
        demotions.record("local", "m", P, 1, 0)
    demotions.record("cli", "s", P, 1, 1)
    assert demotions.window_stats("local")["rate"] == 0.0
    assert demotions.window_stats("cli")["n"] == 1
    assert [r["provider"] for r in demotions.rates_by_provider()] == ["cli", "local"]


def test_torn_log_lines_are_skipped():
    demotions.record("local", "m", P, 2, 0)
    with demotions.LOG_PATH.open("a") as fh:
        fh.write('{"provider": "local", "supported_cl\n')
    assert len(demotions.read_records()) == 1
