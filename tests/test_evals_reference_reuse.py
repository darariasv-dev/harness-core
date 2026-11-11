import json

from harness_core import evals


def test_tier_dir_name_keeps_the_baseline_study_in_the_task_dir():
    assert evals.tier_dir_name("t", "cheap") == "t"
    assert evals.tier_dir_name("t", "free") == "t--free"


def test_load_reference_outputs_reads_both_key_spellings_and_skips_failures(tmp_path):
    d = tmp_path / "t"; d.mkdir()
    (d / "spot_check_001.json").write_text(json.dumps({"index": 1, "strong_output": {"a": 1}, "agree": True}))
    (d / "spot_check_002.json").write_text(json.dumps({"index": 2, "strong_raw": {"a": 2}}))
    (d / "spot_check_003.json").write_text(json.dumps({"index": 3, "failure_class": "timeout"}))
    (d / "spot_check_004.json").write_text("not json")
    assert evals.load_reference_outputs("t", tmp_path) == {1: {"a": 1}, 2: {"a": 2}}
    assert evals.load_reference_outputs("missing", tmp_path) == {}
