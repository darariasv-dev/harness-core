#!/usr/bin/env python3
"""End-to-end demonstration of the harness with a FAKE provider -- runs anywhere, makes no
model calls, and exercises every mechanism: gates before calls, routing by purpose, the
ledger, the composite-fingerprint cache (second run = zero calls), per-provider demotion
logging with the escalation rule, the workflow lock, stage persistence, and the checkpoint
block. Read it top to bottom; it is the shortest complete picture of how a project uses
harness_core.

    python examples/minimal_pipeline.py --run-dir /tmp/example-run"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from harness_core import cache, demotions, ledger, router
from harness_core.checkpoint import format_checkpoint_block, parse_checkpoint_block
from harness_core.lock import workflow_lock
from harness_core.providers import ProviderResult
from harness_core.records import GateResult
from harness_core.runner import Stage, run_pipeline

POLICY = {
    "providers": {"claude_cli": {"type": "claude_cli"}},
    "tiers": {"cheap": {"provider": "fake_cheap", "model": "fake-small"}, "strong": {"provider": "fake_strong", "model": "fake-large"}},
    "tasks": {"assess": "cheap", "draft_for_human": "strong"},
    "default_tier": "cheap",
}
PINNED = {"draft_for_human": "strong"}   # in code: no policy edit can move it
PROMPT = "Assess:\n{text}\nCite evidence ids from {ids}. JSON: {{verdict, claims:[{{claim, evidence_id}}]}}"


class FakeProvider:
    """Stands in for claude_cli / ollama. `fabricate` makes it cite evidence that does not exist."""
    def __init__(self, name, fabricate=0):
        self.name, self.fabricate, self.calls = name, fabricate, 0

    def complete(self, prompt, model, json_schema, timeout_seconds):
        self.calls += 1
        claims = [{"claim": "supported by E1", "evidence_id": "E1"}] + [{"claim": "invented", "evidence_id": "E9"}] * self.fabricate
        return ProviderResult(text=json.dumps({"verdict": "accept", "claims": claims}),
                              usage={"measured": True, "input_tokens": len(prompt) // 4, "output_tokens": 20})


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--run-dir", default="runs/example"); args = ap.parse_args()
    run_dir = Path(args.run_dir); run_dir.mkdir(parents=True, exist_ok=True)
    demotions.LOG_PATH = run_dir / "demotions.jsonl"
    providers = {"fake_cheap": FakeProvider("fake_cheap"), "fake_strong": FakeProvider("fake_strong")}
    allowed = {"E1"}

    with workflow_lock("example", path=run_dir / ".workflow.lock"):
        led = ledger.get_connection(run_dir / "ledger.db")
        cache_conn = cache.get_connection(run_dir / "cache.db")

        def discover(seed):            # 1. deterministic: no model
            return [{"id": str(i), "text": t} for i, t in enumerate(seed)]

        def screen(items):             # 2. gates with evidence, BEFORE any call
            out = []
            for it in items:
                it["gates"] = [GateResult("non_empty", bool(it["text"].strip()), f"{len(it['text'])} chars").__dict__]
                if all(g["passed"] for g in it["gates"]):
                    out.append(it)
            return out

        def assess(items):             # 3. the one model stage: cache-first, demotion-logged, escalating
            route = router.resolve_route("assess", POLICY, pinned_tiers=PINNED)
            override = None
            fired = demotions.should_escalate(route.provider)
            if fired:
                override = "strong"
                demotions.record_escalation(route.provider, route.model, "assess", fired["rate"], fired["n"])
                route = router.resolve_route("assess", POLICY, tier_override=override, pinned_tiers=PINNED)
            for it in items:
                key = cache.compute_cache_key({
                    "content_hash": hashlib.sha256(it["text"].encode()).hexdigest(),
                    "context_hash": hashlib.sha256(",".join(sorted(allowed)).encode()).hexdigest(),
                    "prompt_hash": hashlib.sha256(PROMPT.encode()).hexdigest(),
                    "provider_hash": route.provider_hash,
                })
                hit = cache.get_cached(cache_conn, key)
                if hit is not None:
                    it["assessment"], it["cache_hit"] = hit, True; continue
                text = router.call_model(led, PROMPT.format(text=it["text"], ids=sorted(allowed)), "assess", POLICY,
                                         task_id=it["id"], tier_override=override, providers=providers, pinned_tiers=PINNED)
                raw = json.loads(text)
                kept = [c for c in raw["claims"] if c["evidence_id"] in allowed]
                demotions.record(route.provider, route.model, "assess", len(raw["claims"]), len(raw["claims"]) - len(kept))
                it["assessment"] = {"verdict": raw["verdict"], "claims": kept, "demoted": len(raw["claims"]) - len(kept)}
                it["cache_hit"] = False
                cache.save_cached(cache_conn, key, {"provider_hash": route.provider_hash}, it["assessment"])
            return items

        stages = [Stage("discover", discover), Stage("screen", screen), Stage("assess", assess)]
        seed = ["first input", "", "second input", "third input", "fourth", "fifth", "sixth"]

        r1 = run_pipeline(stages, seed, run_dir / "run1")          # 6 cheap calls (1 item screened out)
        r2 = run_pipeline(stages, seed, run_dir / "run2")          # same inputs -> 6 cache hits, 0 calls
        providers["fake_cheap"].fabricate = 1                      # the cheap model starts inventing evidence
        seed3 = [f"new input {i}" for i in range(6)]
        r3 = run_pipeline(stages, seed3, run_dir / "run3")         # 6 cheap calls, 1 of 2 claims demoted each
        r4 = run_pipeline(stages, ["one more"], run_dir / "run4")  # window: 6 demoted / 18 claims = 0.33 > 0.15, n=12 -> strong

    calls = led.execute("SELECT provider, COUNT(*) c FROM headless_calls GROUP BY provider").fetchall()
    summary = {
        "run1_assessed": len(r1["assess"]), "run1_cache_hits": sum(i["cache_hit"] for i in r1["assess"]),
        "run2_cache_hits": sum(i["cache_hit"] for i in r2["assess"]),
        "run3_demoted_claims": sum(i["assessment"]["demoted"] for i in r3["assess"]),
        "run4_answered_by": demotions.read_records()[-1]["provider"],
        "calls_by_provider": {row["provider"]: row["c"] for row in calls},
        "escalations": demotions.escalation_events(),
        "screened_out": len(r1["discover"]) - len(r1["screen"]),
    }
    assert summary["run1_cache_hits"] == 0 and summary["run2_cache_hits"] == 6, summary
    assert summary["run3_demoted_claims"] == 6 and summary["run4_answered_by"] == "fake_strong", summary
    assert summary["calls_by_provider"] == {"fake_cheap": 12, "fake_strong": 1}, summary
    assert len(summary["escalations"]) == 1 and summary["escalations"][0]["rate"] > demotions.ESCALATION_RATE and summary["escalations"][0]["n"] == 12, summary
    block = format_checkpoint_block({
        "COMMAND": "python examples/minimal_pipeline.py", "COMPLETED": json.dumps(summary["calls_by_provider"]),
        "PHASE": "example", "PILOT": "n/a", "USAGE": f"{ledger.calls_today_count(led)} calls today (fake provider)",
        "BLOCKER": "n/a", "NEXT": "copy template/ and replace the stage bodies",
        "UPDATED": datetime.now(timezone.utc).isoformat(),
    })
    assert parse_checkpoint_block(block)["PHASE"] == "example"
    print(json.dumps(summary, indent=2, default=str)); print(); print(block)
    print("\nOK: 1 item gated out before any call; 6 cheap calls once, 6 cache hits on rerun; fabrication rate over the window above 15% -> next call escalated to strong; lock released.")


if __name__ == "__main__":
    main()
