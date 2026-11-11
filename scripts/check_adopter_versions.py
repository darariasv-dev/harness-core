#!/usr/bin/env python3
"""Check that every known adopter project has the CURRENT harness-core version installed in
its own virtualenv. harness-core is meant to be tracked from one place (this repo); a stale
install in an adopter's venv can silently miss real bug fixes shipped in later versions (see
docs/case-study.md -- 0.2.1 and 0.2.2 were both real-bug-fix bumps, not just version churn).
This script is read-only: it reports drift, it does not fix it.

    python scripts/check_adopter_versions.py

Version is read by running the adopter's OWN venv interpreter and importing harness_core,
not by reading pip's dist-info metadata. For an editable install (`pip install -e`), pip
writes dist-info once at install time and never refreshes it as the source's __version__
changes later -- so dist-info can claim an editable install is "0.2.0" when the code that
actually executes (harness_core.__file__ resolves straight into this repo's source tree) is
current. Importing for real is the only way to see what's actually running.

Exits 0 if every found adopter matches the current version, 1 if any adopter is stale or
missing, 2 if the current version itself can't be determined. Known adopters are listed in
ADOPTERS below; an adopter directory that doesn't exist on this machine is reported as
"not found" rather than guessed at.

Only checks each adopter's own `<repo>/.venv` -- a project that also runs real work out of a
SEPARATE venv elsewhere (e.g. a dedicated scheduled-job runner) needs that venv checked by
hand; this script has no way to discover one it isn't told about."""

from __future__ import annotations

import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ADOPTERS = {
    "agent-system": "~/agent-system",
    "Opportunity-Engine": "~/Opportunity-Engine",
    # Not a top-level dir: its real repo lives under the Codex outputs tree. Omitted here until
    # 2026-09-23, which let its venv sit on a non-editable 0.2.2 install unnoticed.
    "Mission Control": "~/Documents/Codex/2026-09-13/i-w/outputs/mission-control",
    # Opportunity-Engine's scheduled sweep runs from its own worktree + venv (its gap 0033);
    # real Auditor calls happen there, not in the interactive checkout above.
    "Opportunity-Engine sweep runner": "~/.opportunity-engine-sweep-runner",
}


def current_version() -> str | None:
    pyproject = os.path.join(REPO_ROOT, "pyproject.toml")
    try:
        with open(pyproject, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else None


def installed_version(adopter_dir: str) -> str | None:
    """Import harness_core inside the adopter's own venv and read its live __version__."""
    python = os.path.join(adopter_dir, ".venv", "bin", "python")
    if not os.path.isfile(python):
        return None
    try:
        result = subprocess.run(
            [python, "-c", "import harness_core; print(harness_core.__version__)"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def main() -> int:
    current = current_version()
    if current is None:
        print("ERROR: could not determine current harness-core version from pyproject.toml")
        return 2

    print(f"Current harness-core version: {current}\n")

    drift_found = False
    for name, raw_path in ADOPTERS.items():
        adopter_dir = os.path.expanduser(raw_path)
        if not os.path.isdir(adopter_dir):
            print(f"  [NOT FOUND]  {name} ({raw_path}) -- directory does not exist here")
            drift_found = True
            continue

        version = installed_version(adopter_dir)
        if version is None:
            print(f"  [NO VENV]    {name} -- couldn't import harness_core from "
                  f"{adopter_dir}/.venv; can't confirm what's installed")
            drift_found = True
        elif version == current:
            print(f"  [OK]         {name} -- {version}")
        else:
            print(f"  [STALE]      {name} -- installed {version}, current is {current}")
            drift_found = True

    print()
    if drift_found:
        print("Drift found. A stale adopter venv can silently miss real bug fixes shipped "
              "in a later harness-core version -- see docs/case-study.md.")
        return 1
    print("All known adopters match the current harness-core version.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
