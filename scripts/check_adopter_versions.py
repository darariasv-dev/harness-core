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
missing, 2 if the current version itself can't be determined. Known adopters are read from
an untracked adopters.local.json (see adopters.example.json); an adopter directory that doesn't exist on this machine is reported as
"not found" rather than guessed at.

Only checks each adopter's own `<repo>/.venv` -- a project that also runs real work out of a
SEPARATE venv elsewhere (e.g. a dedicated scheduled-job runner) needs that venv checked by
hand; this script has no way to discover one it isn't told about."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_adopters(path: str = os.path.join(REPO_ROOT, "adopters.local.json")) -> dict:
    """Adopters are machine-specific, so they live in an untracked JSON file
    ({"name": "~/path/to/project", ...}); see adopters.example.json."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


ADOPTERS = load_adopters()


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

    if not ADOPTERS:
        print("No adopters configured. Copy adopters.example.json to adopters.local.json and list your projects.")
        return 0

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
