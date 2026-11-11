from myproject import routing_eval_adapter as adapter


def test_adapter_contract():
    fixtures = adapter.load_fixtures()
    assert fixtures and "text" in fixtures[0]
    prompt, schema = adapter.build_prompt("example_assessment", fixtures[0])
    assert "Example recorded input" in prompt and schema["required"] == ["verdict", "claims"]
    assert adapter.outputs_agree("example_assessment", {"verdict": "accept", "claims": [1]}, {"verdict": "accept", "claims": [1, 2]})
    assert not adapter.outputs_agree("example_assessment", {"verdict": "accept", "claims": []}, {"verdict": "reject", "claims": []})
