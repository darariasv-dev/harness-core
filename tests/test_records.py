from harness_core.records import GateResult, OpenStatusEvidence, UsageRecord


def test_gate_result_shape():
    g = GateResult(name="years", passed=True, evidence="2 >= 2")
    assert g.name == "years"
    assert g.passed is True


def test_usage_record_defaults_none():
    u = UsageRecord()
    assert u.input is None and u.output is None


def test_open_status_evidence_defaults():
    e = OpenStatusEvidence()
    assert e.status is None
    assert e.redirect_chain == []
