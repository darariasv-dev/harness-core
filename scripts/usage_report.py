#!/usr/bin/env python3
"""Print a ledger's usage: per purpose, then per provider/model. Measured (provider-reported)
figures and chars/4 estimates are shown in separate columns and never summed.

    python scripts/usage_report.py data/ledger.db [--days 7]

Multi-ledger mode combines several ledgers under caller-supplied labels into one report plus
a grand total -- e.g. one label per consuming project, so "how much am I spending in total,
across everything" has a real, single-command answer instead of N separate reports someone
has to add up by hand. A label's source may be a single path OR a glob pattern (some
consumers keep one ledger PER RUN rather than one persistent file -- e.g.
`data/pipeline/runs/*/ledger.db` -- and every matched file under that label is summed
together). This module has no opinion about what a label names or how many projects exist;
that mapping is the caller's own (see harness_core's own no-domain-words boundary -- a
specific project's ledger paths belong in that caller's own wrapper script, not here).

    python scripts/usage_report.py --multi \
        alpha=~/code/project-alpha/data/ledger.db \
        beta='~/code/project-beta/data/runs/*/ledger.db' \
        [--days 7]"""
from __future__ import annotations

import argparse
from glob import glob
from pathlib import Path

from harness_core import ledger as ledger_module

_SUM_FIELDS = (
    "call_count", "success_count", "failure_count",
    "measured_call_count", "measured_input_tokens", "measured_output_tokens",
    "measured_cache_read_tokens", "measured_cache_creation_tokens", "measured_thinking_tokens",
    "total_prompt_chars", "total_response_chars", "est_prompt_tokens", "est_response_tokens",
)


def _resolve_paths(spec: str) -> list[Path]:
    """A glob pattern's matches, else the literal path if it exists, else nothing (a label
    with no matched files yet -- e.g. a project that hasn't made a real call yet -- is
    reported as zero, never an error)."""
    expanded = str(Path(spec).expanduser())
    matches = sorted(Path(p) for p in glob(expanded))
    if matches:
        return matches
    literal = Path(expanded)
    return [literal] if literal.exists() else []


def _zero_totals() -> dict:
    return {field: 0 for field in _SUM_FIELDS} | {"total_cost_usd": 0.0, "_has_cost": False}


def _add_row(totals: dict, row: dict) -> None:
    for field in _SUM_FIELDS:
        totals[field] += row.get(field) or 0
    cost = row.get("total_cost_usd")
    if cost is not None:
        totals["total_cost_usd"] += cost
        totals["_has_cost"] = True


def _label_totals(paths: list[Path], since_days: int | None) -> dict:
    totals = _zero_totals()
    for path in paths:
        conn = ledger_module.get_connection(path)
        for row in ledger_module.usage_summary(conn, since_days=since_days):
            _add_row(totals, row)
        conn.close()
    return totals


def _format_totals(totals: dict) -> str:
    cost = f"cost=${totals['total_cost_usd']:.4f}" if totals["_has_cost"] else "cost=n/a"
    return (
        f"calls={totals['call_count']:>5} ok={totals['success_count']:>5} "
        f"measured_calls={totals['measured_call_count']:>5} "
        f"in={totals['measured_input_tokens']:>10} out={totals['measured_output_tokens']:>9} "
        f"cache_read={totals['measured_cache_read_tokens']:>9} cache_create={totals['measured_cache_creation_tokens']:>9} "
        f"| est_in={totals['est_prompt_tokens']:>9} est_out={totals['est_response_tokens']:>8} | {cost}"
    )


def _run_single(ledger_path: str, since_days: int | None) -> None:
    conn = ledger_module.get_connection(Path(ledger_path))
    print("per purpose:")
    for r in ledger_module.usage_summary(conn, since_days=since_days):
        print(f"  {r['purpose'][:36]:<36} calls={r['call_count']:>4} ok={r['success_count']:>4} measured={r['measured_call_count']:>4} "
              f"in={r['measured_input_tokens']:>9} cache_read={r['measured_cache_read_tokens']:>9} cache_create={r['measured_cache_creation_tokens']:>9} "
              f"out={r['measured_output_tokens']:>7} | est_in={r['est_prompt_tokens']:>8} est_out={r['est_response_tokens']:>7}")
    print("per provider/model:")
    for r in ledger_module.usage_by_provider(conn, since_days=since_days):
        print(f"  {r['provider']:<12} {r['model'][:28]:<28} {r['purpose'][:32]:<32} calls={r['call_count']:>4} in={r['measured_input_tokens']:>9} out={r['measured_output_tokens']:>7}")


def _run_multi(specs: list[str], since_days: int | None) -> None:
    grand_total = _zero_totals()
    for spec in specs:
        if "=" not in spec:
            raise SystemExit(f"--multi entries must be label=path_or_glob, got {spec!r}")
        label, path_spec = spec.split("=", 1)
        paths = _resolve_paths(path_spec)
        totals = _label_totals(paths, since_days)
        for field in _SUM_FIELDS:
            grand_total[field] += totals[field]
        if totals["_has_cost"]:
            grand_total["total_cost_usd"] += totals["total_cost_usd"]
            grand_total["_has_cost"] = True
        found = f"{len(paths)} ledger file(s)" if paths else "no ledger files found yet"
        print(f"{label:<12} ({found}): {_format_totals(totals)}")
    print(f"{'TOTAL':<12} {'':>16}  {_format_totals(grand_total)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ledger", nargs="?", help="single-ledger mode: path to one ledger.db")
    ap.add_argument("--multi", nargs="+", metavar="LABEL=PATH_OR_GLOB", help="multi-ledger mode: combine several labeled ledgers (or per-run glob patterns) into one report plus a grand total")
    ap.add_argument("--days", type=int, default=None)
    args = ap.parse_args()

    if args.multi:
        _run_multi(args.multi, args.days)
    elif args.ledger:
        _run_single(args.ledger, args.days)
    else:
        ap.error("provide a ledger path, or --multi label=path_or_glob ...")


if __name__ == "__main__":
    main()
