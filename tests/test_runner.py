import json
from dataclasses import dataclass

from harness_core.runner import Stage, run_pipeline


@dataclass
class Item:
    value: int


def test_run_pipeline_chains_stages_and_persists_jsonl(tmp_path):
    stage_a = Stage(name="double", fn=lambda items: [Item(value=i.value * 2) for i in items])
    stage_b = Stage(name="add_one", fn=lambda items: [Item(value=i.value + 1) for i in items])

    results = run_pipeline([stage_a, stage_b], [Item(value=1), Item(value=2)], tmp_path)

    assert [i.value for i in results["double"]] == [2, 4]
    assert [i.value for i in results["add_one"]] == [3, 5]

    double_lines = (tmp_path / "double.jsonl").read_text().splitlines()
    assert json.loads(double_lines[0]) == {"value": 2}
    add_one_lines = (tmp_path / "add_one.jsonl").read_text().splitlines()
    assert json.loads(add_one_lines[1]) == {"value": 5}


def test_run_pipeline_with_custom_to_dict(tmp_path):
    stage = Stage(name="only", fn=lambda items: items)
    run_pipeline([stage], [{"a": 1}], tmp_path, to_dict=lambda x: x)
    lines = (tmp_path / "only.jsonl").read_text().splitlines()
    assert json.loads(lines[0]) == {"a": 1}


def test_run_pipeline_empty_input(tmp_path):
    stage = Stage(name="noop", fn=lambda items: items)
    results = run_pipeline([stage], [], tmp_path)
    assert results["noop"] == []
    assert (tmp_path / "noop.jsonl").read_text() == ""
