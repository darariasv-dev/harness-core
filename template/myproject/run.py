"""Command entry point. Every verb runs under the workflow lock; live model calls are gated
by one environment switch (no exceptions, local providers included); the run ends with a
provider report and a checkpoint block."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness_core import ledger as ledger_module
from harness_core.checkpoint import format_checkpoint_block
from harness_core.lock import workflow_lock
from harness_core.runner import Stage, run_pipeline

from myproject import cache as cache_module
from myproject import stages

LIVE_SWITCH = "MYPROJECT_USE_LIVE_MODEL"
LEDGER_PATH = Path("data/ledger.db")


def live_allowed() -> bool:
    return os.environ.get(LIVE_SWITCH) == "1"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("verb", choices=["run", "usage"])
    parser.add_argument("--run-dir", default=f"runs/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
    args = parser.parse_args(argv)

    with workflow_lock():
        ledger = ledger_module.get_connection(LEDGER_PATH)
        if args.verb == "usage":
            for row in ledger_module.usage_by_provider(ledger):
                print(f"{row['provider']:<12} {row['model'][:28]:<28} {row['purpose'][:32]:<32} calls={row['call_count']:>4} "
                      f"in={row['measured_input_tokens']:>8} cached={row['measured_cache_read_tokens']:>8} out={row['measured_output_tokens']:>7}")
            return 0
        if not live_allowed():
            print(f"{LIVE_SWITCH} is not 1 -- refusing to make real model calls.", file=sys.stderr)
            return 2
        cache_conn = cache_module.get_connection()
        report: dict = {}
        pipeline = [
            Stage("discover", stages.discover),
            Stage("screen", stages.screen),
            Stage("assess", lambda items: stages.assess(items, ledger, cache_conn, allowed_ids={"E1"}, report=report)),
        ]
        results = run_pipeline(pipeline, initial_input=["replace me with real input"], run_dir=Path(args.run_dir))
        print(format_checkpoint_block({
            "COMMAND": " ".join(sys.argv[1:]) or "run",
            "COMPLETED": f"{len(results['assess'])} assessed ({report.get('live_calls', 0)} live calls); route {report.get('route')}",
            "PHASE": "run", "PILOT": "n/a",
            "USAGE": f"{ledger_module.calls_today_count(ledger)} ledger calls today",
            "BLOCKER": "n/a", "NEXT": "review runs/<dir>/assess.jsonl",
            "UPDATED": datetime.now(timezone.utc).isoformat(),
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
