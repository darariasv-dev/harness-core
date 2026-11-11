import json
from unittest.mock import patch

import yaml

from harness_core import evals, ledger


def make_conn(tmp_path):
    return ledger.get_connection(tmp_path / "ledger.db")


FIXTURE_POLICY = {"tiers": {"cheap": "model-a", "strong": "model-b"}, "tasks": {}, "default_tier": "cheap"}


def test_decide_tier_proven():
    assert evals.decide_tier(0.9) == ("cheap", "proven")


def test_decide_tier_borderline():
    assert evals.decide_tier(0.8) == ("cheap", "borderline")


def test_decide_tier_escalated():
    assert evals.decide_tier(0.5) == ("strong", "escalated")


def test_decide_tier_no_evidence_escalates():
    assert evals.decide_tier(None) == ("strong", "escalated")


def _build_prompt(fixture):
    return f"prompt for {fixture['id']}", None


def _outputs_agree(a, b):
    return a.get("value") == b.get("value")


def test_run_agreement_eval_full_agreement(tmp_path, db_conn=None):
    conn = make_conn(tmp_path)
    fixtures = [{"id": "1"}, {"id": "2"}]

    def fake_call_model(conn, prompt, purpose, routing_policy, tier_override=None, json_schema=None):
        return json.dumps({"value": "same"})

    with patch("harness_core.evals.router_module.call_model", side_effect=fake_call_model):
        summary = evals.run_agreement_eval(
            conn, "task1", fixtures, FIXTURE_POLICY, _build_prompt, _outputs_agree, tmp_path,
        )
    assert summary["compared"] == 2
    assert summary["agreement_rate"] == 1.0
    assert summary["decision"] == "proven"
    assert (tmp_path / "task1" / "spot_check_001.json").exists()
    assert (tmp_path / "task1" / "summary.json").exists()


def test_run_agreement_eval_resumes_from_disk(tmp_path):
    conn = make_conn(tmp_path)
    fixtures = [{"id": "1"}]
    call_count = {"n": 0}

    def fake_call_model(conn, prompt, purpose, routing_policy, tier_override=None, json_schema=None):
        call_count["n"] += 1
        return json.dumps({"value": "same"})

    with patch("harness_core.evals.router_module.call_model", side_effect=fake_call_model):
        evals.run_agreement_eval(conn, "task1", fixtures, FIXTURE_POLICY, _build_prompt, _outputs_agree, tmp_path)
        evals.run_agreement_eval(conn, "task1", fixtures, FIXTURE_POLICY, _build_prompt, _outputs_agree, tmp_path)
    assert call_count["n"] == 2  # cheap + strong, once -- second run reused the spot-check file


def test_run_agreement_eval_survives_call_failure(tmp_path):
    from harness_core.router import HeadlessCallFailed

    conn = make_conn(tmp_path)
    fixtures = [{"id": "1"}]

    with patch("harness_core.evals.router_module.call_model", side_effect=HeadlessCallFailed("timed out")):
        summary = evals.run_agreement_eval(conn, "task1", fixtures, FIXTURE_POLICY, _build_prompt, _outputs_agree, tmp_path)
    assert summary["call_failures"] == 1
    assert summary["compared"] == 0
    assert summary["decision"] == "escalated"  # no evidence at all


def test_apply_to_policy_escalates_and_preserves_header(tmp_path):
    path = tmp_path / "routing.yaml"
    path.write_text("# Header comment.\ntasks:\n  task1: cheap\n")
    current_policy, _ = (yaml.safe_load(path.read_text()), None)
    summary = {"task": "task1", "agreement_rate": 0.5, "decision": "escalated", "compared": 10, "fixtures_total": 10, "evaluated_at": "now"}
    evals.apply_to_policy(summary, path, current_policy)
    text = path.read_text()
    assert "# Header comment." in text
    reloaded = yaml.safe_load(text)
    assert reloaded["tasks"]["task1"] == "strong"
    assert reloaded["eval_status"]["task1"]["decision"] == "escalated"


def test_decide_tier_names_the_candidate_and_reference_tiers():
    assert evals.decide_tier(0.95, candidate_tier="free", reference_tier="strong") == ("free", "proven")
    assert evals.decide_tier(0.80, candidate_tier="free", reference_tier="strong") == ("free", "borderline")
    assert evals.decide_tier(0.50, candidate_tier="free", reference_tier="strong") == ("strong", "escalated")
    assert evals.decide_tier(None, candidate_tier="free", reference_tier="strong") == ("strong", "escalated")
    assert evals.decide_tier(0.95) == ("cheap", "proven")  # defaults unchanged


def test_run_agreement_eval_reuses_reference_outputs_and_passes_optional_kwargs(tmp_path):
    conn = make_conn(tmp_path)
    fixtures = [{"id": "1"}, {"id": "2"}]
    seen = []

    def fake_call_model(conn, prompt, purpose, routing_policy, tier_override=None, json_schema=None, **kwargs):
        seen.append((tier_override, sorted(kwargs)))
        return json.dumps({"value": "same"})

    fake_providers = {"x": object()}
    with patch("harness_core.evals.router_module.call_model", side_effect=fake_call_model):
        summary = evals.run_agreement_eval(
            conn, "task1", fixtures, FIXTURE_POLICY, _build_prompt, _outputs_agree, tmp_path,
            tiers=("free", "strong"), reference_outputs={1: {"value": "same"}},
            providers=fake_providers, pinned_tiers={"p": "strong"}, timeout_seconds=30, task_dir_name="task1--free",
        )
    assert seen == [("free", ["pinned_tiers", "providers", "timeout_seconds"]),
                    ("free", ["pinned_tiers", "providers", "timeout_seconds"]),
                    ("strong", ["pinned_tiers", "providers", "timeout_seconds"])]
    assert summary["compared"] == 2 and summary["candidate_tier"] == "free" and summary["tier"] == "free"
    record = json.loads((tmp_path / "task1--free" / "spot_check_001.json").read_text())
    assert record["strong_source"] == "reference"
    assert "strong_source" not in json.loads((tmp_path / "task1--free" / "spot_check_002.json").read_text())


def test_run_agreement_eval_records_non_json_output_as_invalid_response(tmp_path):
    conn = make_conn(tmp_path)

    def fake_call_model(conn, prompt, purpose, routing_policy, tier_override=None, json_schema=None):
        return "not json at all"

    with patch("harness_core.evals.router_module.call_model", side_effect=fake_call_model):
        summary = evals.run_agreement_eval(conn, "task1", [{"id": "1"}], FIXTURE_POLICY, _build_prompt, _outputs_agree, tmp_path)
    assert summary["call_failures"] == 1 and summary["compared"] == 0
    record = json.loads((tmp_path / "task1" / "spot_check_001.json").read_text())
    assert record["failure_class"] == "invalid_response"


def test_apply_tier_result_to_policy_flip_rules(tmp_path):
    path = tmp_path / "routing.yaml"
    path.write_text("tasks:\n  task1: cheap\n  pinned: strong\n")
    current = yaml.safe_load(path.read_text())
    proven = {"task": "task1", "agreement_rate": 0.92, "decision": "proven", "compared": 30, "fixtures_total": 30,
              "call_failures": 0, "candidate_tier": "free", "reference_tier": "strong", "evaluated_at": "now"}
    assert evals.apply_tier_result_to_policy(proven, path, current, flip=False) is False
    assert yaml.safe_load(path.read_text())["tasks"]["task1"] == "cheap"
    assert evals.apply_tier_result_to_policy(proven, path, yaml.safe_load(path.read_text()), flip=True) is True
    assert yaml.safe_load(path.read_text())["tasks"]["task1"] == "free"
    pinned = {**proven, "task": "pinned"}
    assert evals.apply_tier_result_to_policy(pinned, path, yaml.safe_load(path.read_text()), flip=True, pinned_purposes=frozenset({"pinned"})) is False
    reloaded = yaml.safe_load(path.read_text())
    assert reloaded["tasks"]["pinned"] == "strong"
    assert reloaded["eval_status_by_tier"]["pinned"]["free"]["decision"] == "proven"
