"""The assess stage with a fake provider: cache-first, capped, demotion-logged, escalating."""
import json

from harness_core import demotions
from harness_core import ledger as ledger_module
from harness_core.providers import ProviderResult

from myproject import cache as cache_module
from myproject import stages
from myproject.router import PINNED_STRONG

POLICY = {
    "providers": {"claude_cli": {"type": "claude_cli"}, "fake_local": {"type": "ollama", "base_url": "http://127.0.0.1:11434"}},
    "tiers": {"free": {"provider": "fake_local", "model": "local"}, "strong": {"provider": "claude_cli", "model": "strong-model"}},
    "tasks": {"example_assessment": "free"}, "default_tier": "free",
}


class FakeProvider:
    def __init__(self, name, fabricate=0):
        self.name, self.fabricate, self.calls = name, fabricate, 0

    def complete(self, prompt, model, json_schema, timeout_seconds):
        self.calls += 1
        claims = [{"claim": "real", "evidence_id": "E1"}] + [{"claim": "made up", "evidence_id": "none"}] * self.fabricate
        return ProviderResult(text=json.dumps({"verdict": "accept", "claims": claims}), usage={"measured": True, "input_tokens": 10, "output_tokens": 5})


def _run(tmp_path, providers, texts=("alpha", "beta"), report=None):
    ledger = ledger_module.get_connection(tmp_path / "ledger.db")
    cache_conn = cache_module.get_connection(tmp_path / "cache.db")
    items = stages.screen(stages.discover(list(texts)))
    return stages.assess(items, ledger, cache_conn, allowed_ids={"E1"}, routing_policy=POLICY, providers=providers, report=report), ledger


def test_screen_gate_blocks_empty_items_before_any_call(tmp_path):
    assert [i.id for i in stages.screen(stages.discover(["", "x"]))] == ["1"]


def test_second_run_over_unchanged_input_is_a_cache_hit(tmp_path):
    local = FakeProvider("fake_local")
    providers = {"fake_local": local, "claude_cli": FakeProvider("claude_cli")}
    out1, ledger = _run(tmp_path, providers)
    out2, _ = _run(tmp_path, providers)
    assert local.calls == 2 and all(i.cache_hit for i in out2) and not any(i.cache_hit for i in out1)
    assert ledger.execute("SELECT COUNT(*) FROM headless_calls").fetchone()[0] == 2


def test_fabricated_claims_are_demoted_and_logged_per_provider(tmp_path):
    out, _ = _run(tmp_path, {"fake_local": FakeProvider("fake_local", fabricate=1), "claude_cli": FakeProvider("claude_cli")}, texts=("a",))
    assert out[0].assessment["claims"] == [{"claim": "real", "evidence_id": "E1"}] and out[0].assessment["demoted"] == 1
    rec = demotions.read_records()[-1]
    assert (rec["provider"], rec["supported_claims"], rec["demoted"]) == ("fake_local", 2, 1)


def test_rate_above_15_percent_escalates_the_run_to_strong(tmp_path):
    for _ in range(5):
        demotions.record("fake_local", "local", stages.PURPOSE, supported_claims=4, demoted=1)
    local, strong = FakeProvider("fake_local"), FakeProvider("claude_cli")
    report = {}
    _run(tmp_path, {"fake_local": local, "claude_cli": strong}, texts=("a",), report=report)
    assert local.calls == 0 and strong.calls == 1
    assert report["route"]["tier"] == "strong" and report["escalation"]["rate"] == 0.25
    assert demotions.escalation_events()[-1]["provider"] == "fake_local"


def test_pinned_purposes_are_a_code_change_not_a_policy_edit():
    assert "draft_for_human" in PINNED_STRONG
