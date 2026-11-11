"""Pipeline stages. Contract: each stage is `list -> list` so harness_core.runner.run_pipeline
can sequence them and persist each output as JSONL. Order the stages so that everything
deterministic (discover, screen, gates) runs BEFORE the one stage that calls a model, and
that stage is cache-first."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Optional

from harness_core import demotions
from harness_core.records import GateResult

from myproject import cache as cache_module
from myproject import router

PURPOSE = "example_assessment"
PROMPT_TEMPLATE = (
    "Assess the item below. Respond with JSON matching the schema: verdict (accept|reject), "
    "claims (a list of {{claim, evidence_id}}) where evidence_id is one of the allowed ids: {allowed_ids}.\n\n"
    "ITEM:\n{text}\n"
)
JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["accept", "reject"]},
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "claim": {"type": "string"}, "evidence_id": {"type": "string"}}, "required": ["claim", "evidence_id"]}},
    },
    "required": ["verdict", "claims"],
}
MAX_LIVE_CALLS_PER_RUN = 10


@dataclass
class Item:
    id: str
    text: str
    gates: list = field(default_factory=list)
    assessment: Optional[dict] = None
    cache_hit: bool = False

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def discover(seed: list) -> list:
    """Produce the initial items (a fetch, a file, a query). No model calls."""
    return [Item(id=str(i), text=t) for i, t in enumerate(seed)]


def screen(items: list) -> list:
    """Deterministic gates with evidence -- an item that fails never costs a model call."""
    out = []
    for item in items:
        item.gates = [GateResult("non_empty", bool(item.text.strip()), f"{len(item.text)} chars")]
        if all(g.passed for g in item.gates):
            out.append(item)
    return out


def _validate(raw: dict, allowed_ids: set) -> tuple:
    """The project's own fabrication check: a claim citing no allowed evidence id is demoted.
    Returns (validated_assessment, supported_claims, demoted)."""
    kept, demoted = [], 0
    for claim in raw.get("claims", []):
        if claim.get("evidence_id") in allowed_ids:
            kept.append(claim)
        else:
            demoted += 1
    return {"verdict": raw.get("verdict"), "claims": kept, "demoted": demoted}, len(raw.get("claims", [])), demoted


def assess(items: list, ledger: sqlite3.Connection, cache_conn: sqlite3.Connection, allowed_ids: set,
           routing_policy: Optional[dict] = None, providers: Optional[dict] = None, report: Optional[dict] = None) -> list:
    """Cache-first, budget-capped, demotion-logged model stage."""
    policy = routing_policy if routing_policy is not None else router.load_routing_policy()
    routing_hash = router.routing_policy_hash() if routing_policy is None else hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
    prompt_hash = hashlib.sha256(PROMPT_TEMPLATE.encode()).hexdigest()
    context_hash = hashlib.sha256(",".join(sorted(allowed_ids)).encode()).hexdigest()

    tier_override = None
    route = router.resolve_route(PURPOSE, policy)
    escalation = None
    if route.tier != router.STRONG_TIER:
        fired = demotions.should_escalate(route.provider)
        if fired:
            tier_override = router.STRONG_TIER
            escalation = {"from": asdict(route), "rate": fired["rate"], "n": fired["n"]}
            route = router.resolve_route(PURPOSE, policy, tier_override=tier_override)
            demotions.record_escalation(escalation["from"]["provider"], escalation["from"]["model"], PURPOSE, fired["rate"], fired["n"])
    provider_hash = route.provider_hash

    live_calls = 0
    for item in items:
        key = cache_module.compute_cache_key(item.content_hash, context_hash=context_hash, prompt_hash=prompt_hash,
                                             routing_hash=routing_hash, provider_hash=provider_hash)
        cached = cache_module.get_cached(cache_conn, key)
        if cached is not None:
            item.assessment, item.cache_hit = cached, True
            continue
        if live_calls >= MAX_LIVE_CALLS_PER_RUN:
            break
        prompt = PROMPT_TEMPLATE.format(allowed_ids=sorted(allowed_ids), text=item.text)
        text = router.call_model(ledger, prompt, PURPOSE, task_id=item.id, json_schema=JSON_SCHEMA,
                                 routing_policy=policy, tier_override=tier_override, providers=providers)
        live_calls += 1
        assessment, claims, demoted = _validate(json.loads(text), allowed_ids)
        demotions.record(route.provider, route.model, PURPOSE, claims, demoted)
        cache_module.save(cache_conn, key, assessment, item.content_hash, context_hash=context_hash,
                          prompt_hash=prompt_hash, routing_hash=routing_hash, provider_hash=provider_hash)
        item.assessment = assessment
    if report is not None:
        report.update({"route": asdict(route), "live_calls": live_calls, "escalation": escalation,
                       "demotion_rates": demotions.rates_by_provider()})
    return [i for i in items if i.assessment is not None]
