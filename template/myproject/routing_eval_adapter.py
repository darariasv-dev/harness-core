"""What the generic agreement study (scripts/eval_routing.py in the harness repo) needs from
a project: real recorded fixtures, a prompt per (task, fixture), and what "agreement" means
for that task's OUTPUT. Agreement is outcome agreement, not verbatim-text agreement -- two
tiers paraphrasing the same content differently must not count as a disagreement."""
from __future__ import annotations

import json
from pathlib import Path

from myproject import stages

FIXTURES_DIR = Path("tests/fixtures/routing_eval")
TASKS = ["example_assessment"]


def load_fixtures(fixtures_dir: Path = FIXTURES_DIR) -> list:
    """30-50 REAL recorded inputs per task, one JSON file each: {"text": "..."}."""
    return [json.loads(p.read_text()) for p in sorted(fixtures_dir.glob("fixture_*.json"))]


def build_prompt(task: str, fixture: dict) -> tuple:
    if task == "example_assessment":
        return stages.PROMPT_TEMPLATE.format(allowed_ids=fixture.get("allowed_ids", []), text=fixture["text"]), stages.JSON_SCHEMA
    raise ValueError(f"unknown task {task!r}")


def outputs_agree(task: str, a: dict, b: dict) -> bool:
    if task == "example_assessment":
        return a.get("verdict") == b.get("verdict") and abs(len(a.get("claims", [])) - len(b.get("claims", []))) <= 1
    raise ValueError(f"unknown task {task!r}")
