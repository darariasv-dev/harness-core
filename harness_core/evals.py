"""A generic multi-tier agreement study: send the SAME real input through two model tiers
(a candidate tier and a strong reference) via harness_core.router.call_model, compare their
outputs with a caller-supplied function, and decide -- via a >=0.90 / 0.75-0.90 / <0.75 rule
-- whether the candidate tier is proven adequate, borderline, or should be escalated to the
reference for that task. Persists one spot-check file per input (never just a sample) plus an
aggregate summary, and is resumable: an input whose spot-check file already exists on disk is
loaded from there instead of re-calling the model, so a run interrupted partway through never
throws away real spend already made.

Reference reuse (router extension, 2026-09-13): `reference_outputs` ({fixture index: parsed
output}) supplies the reference tier's answers from an EARLIER study on the same fixtures, so
evaluating a new candidate tier (a free/local provider) spends zero calls on the reference.
The spot-check record marks such an answer `"<tier>_source": "reference"`.

Deliberately has no opinion about what "agreement" means for any particular task -- a
consuming project supplies both `build_prompt` (turn one fixture into a (prompt, json_schema)
pair) and `outputs_agree` (compare two parsed JSON outputs and return a bool). This module
owns only the call-two-tiers / persist / decide / apply-to-policy machinery."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from harness_core import router as router_module
from harness_core.failures import classify_headless_failure
from harness_core.policy import write_yaml_policy
from harness_core.router import HeadlessCallFailed

AGREEMENT_PROVEN_THRESHOLD = 0.90
AGREEMENT_BORDERLINE_THRESHOLD = 0.75

DECISION_PROVEN = "proven"
DECISION_BORDERLINE = "borderline"
DECISION_ESCALATED = "escalated"


def decide_tier(agreement_rate: Optional[float], candidate_tier: str = "cheap", reference_tier: str = "strong") -> tuple[str, str]:
    """Returns (tier, decision_label). None (no successful comparisons at all) is treated
    conservatively as ESCALATED -- absence of evidence is never treated as proof the
    candidate tier is fine."""
    if agreement_rate is None:
        return reference_tier, DECISION_ESCALATED
    if agreement_rate >= AGREEMENT_PROVEN_THRESHOLD:
        return candidate_tier, DECISION_PROVEN
    if agreement_rate >= AGREEMENT_BORDERLINE_THRESHOLD:
        return candidate_tier, DECISION_BORDERLINE
    return reference_tier, DECISION_ESCALATED


def _call(conn, prompt, purpose, routing_policy, schema, tier, providers, pinned_tiers, timeout_seconds) -> str:
    # Optional kwargs are only passed when set, so a caller's fake call_model with the
    # original fixed signature keeps working.
    extra = {}
    if providers is not None:
        extra["providers"] = providers
    if pinned_tiers is not None:
        extra["pinned_tiers"] = pinned_tiers
    if timeout_seconds is not None:
        extra["timeout_seconds"] = timeout_seconds
    return router_module.call_model(conn, prompt, purpose=purpose, routing_policy=routing_policy, json_schema=schema, tier_override=tier, **extra)


def run_agreement_eval(
    conn: sqlite3.Connection,
    task: str,
    fixtures: list[dict],
    routing_policy: dict,
    build_prompt: Callable[[dict], tuple[str, Optional[dict]]],
    outputs_agree: Callable[[dict, dict], bool],
    out_dir: Path,
    tiers: tuple[str, str] = ("cheap", "strong"),
    reuse_existing: bool = True,
    reference_outputs: Optional[dict] = None,
    providers: Optional[dict] = None,
    pinned_tiers: Optional[dict] = None,
    timeout_seconds: Optional[int] = None,
    task_dir_name: Optional[str] = None,
    on_fixture: Optional[Callable[[dict], None]] = None,
) -> dict:
    """`build_prompt(fixture) -> (prompt_text, json_schema_or_None)`. `outputs_agree(a, b) ->
    bool` compares two parsed JSON outputs. Resilient to a per-call failure (timeout, rate
    limit, etc.) -- that fixture is recorded as a failed comparison and excluded from the
    agreement rate, never silently counted as agreement or disagreement.

    `reuse_existing=True` (default): a fixture whose spot_check file already exists on disk
    is loaded from there instead of re-calling the model -- real spend already made is never
    thrown away just because a later fixture in the same run crashed or was interrupted.
    `task_dir_name` (default `task`) lets one task's studies for different candidate tiers
    live side by side. `on_fixture(record)` is called after each fixture is persisted."""
    task_dir = out_dir / (task_dir_name or task)
    task_dir.mkdir(parents=True, exist_ok=True)

    comparisons = []
    call_failures = []
    tier_a, tier_b = tiers
    reference_outputs = reference_outputs or {}
    for i, fixture in enumerate(fixtures, start=1):
        spot_check_path = task_dir / f"spot_check_{i:03d}.json"
        if reuse_existing and spot_check_path.exists():
            record = json.loads(spot_check_path.read_text())
            (comparisons if "agree" in record else call_failures).append(record)
            continue

        prompt, schema = build_prompt(fixture)
        record: dict = {"index": i}
        started = datetime.now(timezone.utc)
        try:
            text_a = _call(conn, prompt, task, routing_policy, schema, tier_a, providers, pinned_tiers, timeout_seconds)
            record[f"{tier_a}_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
            if i in reference_outputs:
                output_b = reference_outputs[i]
                record[f"{tier_b}_source"] = "reference"
            else:
                text_b = _call(conn, prompt, task, routing_policy, schema, tier_b, providers, pinned_tiers, timeout_seconds)
                output_b = json.loads(text_b)
            output_a = json.loads(text_a)
        except HeadlessCallFailed as exc:
            record["failure_class"] = classify_headless_failure(exc).value
            record["error"] = str(exc)
            call_failures.append(record)
            spot_check_path.write_text(json.dumps(record, indent=2))
            if on_fixture:
                on_fixture(record)
            continue
        except json.JSONDecodeError as exc:
            record["failure_class"] = "invalid_response"
            record["error"] = f"non-JSON output: {exc}"
            call_failures.append(record)
            spot_check_path.write_text(json.dumps(record, indent=2))
            if on_fixture:
                on_fixture(record)
            continue

        agree = outputs_agree(output_a, output_b)
        record.update({f"{tier_a}_output": output_a, f"{tier_b}_output": output_b, "agree": agree})
        comparisons.append(record)
        spot_check_path.write_text(json.dumps(record, indent=2))
        if on_fixture:
            on_fixture(record)

    n_compared = len(comparisons)
    agreement_rate = (sum(1 for c in comparisons if c["agree"]) / n_compared) if n_compared else None
    tier, decision = decide_tier(agreement_rate, candidate_tier=tier_a, reference_tier=tier_b)

    summary = {
        "task": task, "fixtures_total": len(fixtures), "compared": n_compared,
        "call_failures": len(call_failures), "agreement_rate": agreement_rate,
        "decision": decision, "tier": tier,
        "candidate_tier": tier_a, "reference_tier": tier_b,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    (task_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def tier_dir_name(task: str, candidate_tier: str, baseline_tier: str = "cheap") -> str:
    """The baseline candidate's study lives in `<task>/`; any other candidate tier in
    `<task>--<tier>/`, so two studies never overwrite each other's spot-check files."""
    return task if candidate_tier == baseline_tier else f"{task}--{candidate_tier}"


def load_reference_outputs(task: str, out_dir: Path, reference_tier: str = "strong") -> dict:
    """{fixture index: parsed reference output} from an earlier study's spot-check files under
    `out_dir/<task>/`. Only indices holding a real reference output are returned (failed
    comparisons are skipped, so a later run re-calls the reference for those). Accepts both
    `<tier>_output` and the older `<tier>_raw` key spelling."""
    task_dir = out_dir / task
    outputs: dict = {}
    if not task_dir.exists():
        return outputs
    for path in sorted(task_dir.glob("spot_check_*.json")):
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or "index" not in record:
            continue
        for key in (f"{reference_tier}_output", f"{reference_tier}_raw"):
            if isinstance(record.get(key), dict):
                outputs[int(record["index"])] = record[key]
                break
    return outputs


def apply_to_policy(summary: dict, policy_path: Path, current_policy: dict) -> None:
    """Writes the real evidence into the routing policy file itself -- `tasks[task]` is only
    ever CHANGED to "strong" (an escalation on real evidence of disagreement); a "proven" or
    "borderline" result never downgrades an already-strong task back to cheap automatically.
    `eval_status[task]` always records the real measured evidence regardless of outcome."""
    task = summary["task"]
    policy = dict(current_policy)
    if summary["decision"] == DECISION_ESCALATED:
        policy.setdefault("tasks", {})[task] = "strong"
    policy.setdefault("eval_status", {})[task] = {
        "agreement_rate": summary["agreement_rate"], "decision": summary["decision"],
        "compared": summary["compared"], "fixtures_total": summary["fixtures_total"],
        "evaluated_at": summary["evaluated_at"],
    }
    write_yaml_policy(policy_path, policy)


def apply_tier_result_to_policy(
    summary: dict,
    policy_path: Path,
    current_policy: dict,
    flip: bool = False,
    pinned_purposes: frozenset = frozenset(),
) -> bool:
    """For a candidate-tier study (e.g. `free` vs `strong`): ALWAYS records the measurement
    under `eval_status_by_tier[task][candidate_tier]`; moves `tasks[task]` to the candidate
    tier ONLY when `flip` is requested, the decision is PROVEN (>= 0.90), and the task is not
    a pinned purpose. Borderline never flips. Returns whether a flip was written."""
    task = summary["task"]
    candidate = summary.get("candidate_tier", "cheap")
    policy = dict(current_policy)
    policy.setdefault("eval_status_by_tier", {}).setdefault(task, {})[candidate] = {
        "agreement_rate": summary["agreement_rate"], "decision": summary["decision"],
        "compared": summary["compared"], "fixtures_total": summary["fixtures_total"],
        "call_failures": summary.get("call_failures"), "reference_tier": summary.get("reference_tier"),
        "evaluated_at": summary["evaluated_at"],
    }
    flipped = False
    if flip and summary["decision"] == DECISION_PROVEN and task not in pinned_purposes:
        policy.setdefault("tasks", {})[task] = candidate
        flipped = True
    write_yaml_policy(policy_path, policy)
    return flipped
