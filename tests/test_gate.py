from harness_core.gate import all_passed, failed_gates, summarize
from harness_core.records import GateResult


def _gates():
    return [
        GateResult(name="a", passed=True, evidence="ok"),
        GateResult(name="b", passed=False, evidence="missing"),
    ]


def test_all_passed_false_when_one_fails():
    assert all_passed(_gates()) is False
    assert all_passed([GateResult(name="a", passed=True, evidence="ok")]) is True


def test_failed_gates_returns_only_failures():
    failed = failed_gates(_gates())
    assert len(failed) == 1
    assert failed[0].name == "b"


def test_summarize_shows_pass_fail_and_evidence():
    text = summarize(_gates())
    assert "a: PASS -- ok" in text
    assert "b: FAIL -- missing" in text
