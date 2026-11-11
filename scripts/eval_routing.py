#!/usr/bin/env python3
"""Generic model-routing agreement study. Sends the SAME real inputs through a candidate tier
and the strong reference, compares OUTCOMES with the project's own rule, and writes the
measured evidence into the routing policy. A task moves to a cheaper tier only on PROVEN
(>= 0.90 agreement) and never if it is pinned in code.

    python scripts/eval_routing.py --adapter myproject.routing_eval_adapter \
        --policy policy/model_routing.v1.yaml --ledger data/routing_eval/ledger.db \
        --out data/routing_eval --tasks example_assessment                    # cheap vs strong
    python scripts/eval_routing.py ... --provider ollama --apply-flips        # free vs stored strong

The adapter module must expose: load_fixtures() -> list[dict]; build_prompt(task, fixture)
-> (prompt, json_schema|None); outputs_agree(task, a, b) -> bool; optionally PINNED_TIERS
(dict) and RESTRICTED_FLAGS (list). Real calls require --live-env-var (default
HARNESS_USE_LIVE_MODEL) to be "1" -- one switch, local providers included."""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from harness_core import evals, ledger as ledger_module, router  # noqa: E402
from harness_core.policy import load_yaml_policy  # noqa: E402

LOCAL_CALL_TIMEOUT_SECONDS = 900


def _candidate_tier_for(policy: dict, provider_name: str) -> str:
    for tier_name, spec in (policy.get("tiers") or {}).items():
        if isinstance(spec, dict) and spec.get("provider") == provider_name:
            return tier_name
    raise SystemExit(f"no tier uses provider {provider_name!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True, help="module path exposing load_fixtures/build_prompt/outputs_agree")
    ap.add_argument("--policy", default="policy/model_routing.v1.yaml")
    ap.add_argument("--ledger", default="data/routing_eval/ledger.db")
    ap.add_argument("--out", default="data/routing_eval")
    ap.add_argument("--tasks", nargs="+", required=True)
    ap.add_argument("--max-fixtures", type=int, default=None)
    ap.add_argument("--provider", default=None, help="candidate provider (e.g. ollama); default candidate tier is cheap")
    ap.add_argument("--tier", default=None)
    ap.add_argument("--reference-tier", default="strong")
    ap.add_argument("--apply-flips", action="store_true")
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument("--no-reference-reuse", action="store_true")
    ap.add_argument("--live-env-var", default="HARNESS_USE_LIVE_MODEL")
    args = ap.parse_args()

    if os.environ.get(args.live_env_var) != "1":
        print(f"{args.live_env_var} is not 1 -- refusing to make real model calls."); return

    adapter = importlib.import_module(args.adapter)
    policy_path = Path(args.policy); policy = load_yaml_policy(policy_path)[0]
    pinned = getattr(adapter, "PINNED_TIERS", {}) or {}
    providers = router.build_providers(policy, extra_flags=getattr(adapter, "RESTRICTED_FLAGS", None))
    candidate = args.tier or (_candidate_tier_for(policy, args.provider) if args.provider else "cheap")
    timeout = args.timeout or (LOCAL_CALL_TIMEOUT_SECONDS if args.provider else None)
    if args.provider:
        p = providers.get(args.provider)
        if p is None:
            raise SystemExit(f"provider {args.provider!r} is not enabled in {policy_path}")
        if hasattr(p, "is_available") and not p.is_available():
            raise SystemExit(f"{args.provider} not reachable -- {p.start_hint()}")

    fixtures = adapter.load_fixtures()[: args.max_fixtures or None]
    out_dir = Path(args.out)
    conn = ledger_module.get_connection(Path(args.ledger))
    print(f"{len(fixtures)} fixtures; candidate {candidate!r} vs reference {args.reference_tier!r}")

    for task in args.tasks:
        if task in pinned:
            print(f"\n=== {task}: pinned in code -- not evaluated ==="); continue
        refs = {} if args.no_reference_reuse else evals.load_reference_outputs(task, out_dir, args.reference_tier)
        refs = {i: o for i, o in refs.items() if i <= len(fixtures)}
        print(f"\n=== {task}: {len(refs)} reference outputs reused, up to {len(fixtures) + len(fixtures) - len(refs)} real calls ===")

        def progress(rec, _t=candidate):
            if "agree" in rec:
                print(f"  fixture {rec['index']:>3}: agree={rec['agree']} ({rec.get(f'{_t}_seconds', '?')}s)", flush=True)
            else:
                print(f"  fixture {rec['index']:>3}: FAILED {rec.get('failure_class')} -- {str(rec.get('error'))[:120]}", flush=True)

        summary = evals.run_agreement_eval(
            conn, task, fixtures, policy,
            build_prompt=lambda f, _t=task: adapter.build_prompt(_t, f),
            outputs_agree=lambda a, b, _t=task: adapter.outputs_agree(_t, a, b),
            out_dir=out_dir, tiers=(candidate, args.reference_tier), reference_outputs=refs,
            providers=providers, pinned_tiers=pinned, timeout_seconds=timeout,
            task_dir_name=evals.tier_dir_name(task, candidate), on_fixture=progress,
        )
        print(f"  compared={summary['compared']}/{summary['fixtures_total']} failures={summary['call_failures']} "
              f"agreement={summary['agreement_rate']} decision={summary['decision']}")
        current = load_yaml_policy(policy_path)[0]
        if candidate == "cheap":
            evals.apply_to_policy(summary, policy_path, current); print(f"  {policy_path}: eval_status[{task!r}] recorded")
        else:
            flipped = evals.apply_tier_result_to_policy(summary, policy_path, current, flip=args.apply_flips, pinned_purposes=frozenset(pinned))
            print(f"  {policy_path}: eval_status_by_tier[{task!r}][{candidate!r}] recorded; tasks[{task!r}] {'-> ' + candidate if flipped else 'unchanged'}")

    print("\nusage by provider:")
    for row in ledger_module.usage_by_provider(conn):
        print(f"  {row['provider']:<12} {row['model'][:28]:<28} {row['purpose'][:32]:<32} calls={row['call_count']:>4} "
              f"ok={row['success_count']:>4} in={row['measured_input_tokens']:>9} out={row['measured_output_tokens']:>7}")


if __name__ == "__main__":
    main()
