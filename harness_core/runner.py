"""A generic multi-stage pipeline runner: a named, ordered sequence of stage functions, each
taking the previous stage's output list and returning the next stage's, with each stage's
output persisted as JSONL under a run directory. Has no opinion about what a "stage" computes
-- discover/screen/fetch/assess/draft-style pipelines are a consuming project's own concept,
supplied here only as plain callables."""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class Stage:
    name: str
    fn: Callable[[list], list]


def _default_to_dict(record: Any) -> Any:
    return dataclasses.asdict(record) if dataclasses.is_dataclass(record) else record


def _write_jsonl(path: Path, records: list, to_dict: Callable[[Any], Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for record in records:
            f.write(json.dumps(to_dict(record), default=str) + "\n")


def run_pipeline(
    stages: list[Stage],
    initial_input: list,
    run_dir: Path,
    to_dict: Optional[Callable[[Any], Any]] = None,
) -> dict[str, list]:
    """Runs each stage in order, feeding the previous stage's output list as the next
    stage's input, and writes each stage's output to `run_dir/<stage_name>.jsonl`. Returns
    {stage_name: output_list} so a caller can inspect any intermediate stage's result, not
    just the last one."""
    to_dict = to_dict or _default_to_dict
    results: dict[str, list] = {}
    current = initial_input
    for stage in stages:
        current = stage.fn(current)
        results[stage.name] = current
        _write_jsonl(run_dir / f"{stage.name}.jsonl", current, to_dict)
    return results
