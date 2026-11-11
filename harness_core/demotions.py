"""Per-provider demotion log and the auto-escalation rule.

A consuming project decides what a "demotion" is -- typically a model output that asserts
support for something while citing no valid evidence identifier, i.e. the project's measured
signal that a model is making things up. This module only records, per call, how many
supported claims a provider+model made and how many of them the project's own validation
demoted, and answers one question: should the next call be escalated to the reference tier?

The rule: over a provider's last WINDOW records, once at least MIN_RECORDS exist, if
demoted / supported_claims is strictly above ESCALATION_RATE, escalate. Exactly the rate does
not escalate. An escalation is appended as an event so it shows up in run summaries; this
never edits the routing policy -- moving a task between tiers permanently belongs to the
agreement study (harness_core.evals). The log is an append-only JSONL file; a torn line never
poisons the window."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOG_PATH = Path("demotions.jsonl")

ESCALATION_RATE = 0.15
MIN_RECORDS = 5
WINDOW = 20
ACTION_ESCALATED = "escalated_to_strong"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(path: Optional[Path]) -> Path:
    # Resolved at call time on purpose, so tests can point LOG_PATH at a temp file.
    return path if path is not None else LOG_PATH


def _append(record: dict, path: Optional[Path]) -> None:
    target = _path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def record(provider: str, model: str, purpose: str, supported_claims: int, demoted: int,
           path: Optional[Path] = None, now: Optional[str] = None) -> dict:
    entry = {"at": now or _now(), "provider": provider, "model": model, "purpose": purpose,
             "supported_claims": int(supported_claims), "demoted": int(demoted)}
    _append(entry, path)
    return entry


def record_escalation(provider: str, model: str, purpose: str, rate: float, n: int,
                      path: Optional[Path] = None, now: Optional[str] = None) -> dict:
    entry = {"at": now or _now(), "provider": provider, "model": model, "purpose": purpose,
             "action": ACTION_ESCALATED, "rate": round(rate, 4), "n": int(n)}
    _append(entry, path)
    return entry


def read_records(path: Optional[Path] = None) -> list:
    target = _path(path)
    if not target.exists():
        return []
    records = []
    for line in target.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def window_stats(provider: str, path: Optional[Path] = None, window: int = WINDOW) -> dict:
    """{provider, n, supported_claims, demoted, rate} over the provider's last `window`
    records (escalation events excluded). `rate` is None when no supported claims exist."""
    rows = [r for r in read_records(path) if r.get("provider") == provider and "supported_claims" in r][-window:]
    claims = sum(int(r.get("supported_claims") or 0) for r in rows)
    demoted = sum(int(r.get("demoted") or 0) for r in rows)
    rate = (demoted / claims) if claims else None
    return {"provider": provider, "n": len(rows), "supported_claims": claims, "demoted": demoted, "rate": rate}


def should_escalate(provider: str, path: Optional[Path] = None) -> Optional[dict]:
    """The window stats when the rule fires, else None."""
    stats = window_stats(provider, path)
    if stats["n"] < MIN_RECORDS or stats["rate"] is None:
        return None
    return stats if stats["rate"] > ESCALATION_RATE else None


def rates_by_provider(path: Optional[Path] = None) -> list:
    providers = sorted({r.get("provider") for r in read_records(path) if r.get("provider") and "supported_claims" in r})
    return [window_stats(p, path) for p in providers]


def escalation_events(path: Optional[Path] = None, limit: int = 10) -> list:
    return [r for r in read_records(path) if r.get("action") == ACTION_ESCALATED][-limit:]
