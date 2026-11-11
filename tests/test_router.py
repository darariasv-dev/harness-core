import json
import os
from unittest.mock import MagicMock, patch

import pytest

from harness_core import ledger, router


def make_conn(tmp_path):
    return ledger.get_connection(tmp_path / "ledger.db")


FIXTURE_POLICY = {
    "tiers": {"cheap": "model-a", "strong": "model-b"},
    "tasks": {"task1": "cheap", "task2": "strong"},
    "default_tier": "cheap",
}


def test_resolve_model_uses_mapped_tier():
    model, tier = router.resolve_model("task1", FIXTURE_POLICY)
    assert model == "model-a" and tier == "cheap"


def test_resolve_model_escalates():
    model, tier = router.resolve_model("task2", FIXTURE_POLICY)
    assert model == "model-b" and tier == "strong"


def test_resolve_model_falls_back_to_default_tier():
    model, tier = router.resolve_model("unknown_task", FIXTURE_POLICY)
    assert tier == "cheap" and model == "model-a"


def test_resolve_model_tier_override():
    model, tier = router.resolve_model("task1", FIXTURE_POLICY, tier_override="strong")
    assert model == "model-b" and tier == "strong"


def test_resolve_model_never_blocks_on_empty_policy():
    model, tier = router.resolve_model("anything", {})
    assert model == router._FALLBACK_MODEL
    assert tier == router._FALLBACK_TIER


def test_fallback_default_is_the_strong_tier_on_sonnet():
    """0.5.0: an unclassified purpose gets Sonnet, never a silent drop to the cheapest model
    and never a silent climb to a higher one."""
    assert router._FALLBACK_TIER == "strong"
    assert "sonnet" in router._FALLBACK_MODEL


def test_policy_without_a_default_tier_routes_unlisted_purposes_to_strong():
    policy = {"tiers": {"cheap": "model-a", "strong": "model-b", "top": "model-c"}, "tasks": {"task1": "cheap"}}
    assert router.resolve_model("unknown_task", policy) == ("model-b", "strong")
    assert router.resolve_model("task1", policy) == ("model-a", "cheap")


def test_a_higher_tier_is_used_only_when_a_purpose_names_it():
    policy = {
        "tiers": {"cheap": "model-a", "strong": "model-b", "top": "model-c"},
        "tasks": {"hard_task": "top"},
        "default_tier": "strong",
    }
    assert router.resolve_model("hard_task", policy) == ("model-c", "top")
    assert router.resolve_model("anything_else", policy) == ("model-b", "strong")
    assert router.resolve_model("pinned_task", policy, pinned_tiers={"pinned_task": "top"}) == ("model-c", "top")


def _fake_completed(returncode, stdout, stderr=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def test_call_model_success(tmp_path):
    conn = make_conn(tmp_path)
    envelope = json.dumps({"result": "hello", "usage": {"input_tokens": 1, "output_tokens": 2}})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)):
        result = router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY)
    assert result == "hello"
    row = conn.execute("SELECT model FROM headless_calls").fetchone()
    assert row["model"] == "model-a"


def test_call_model_uses_strong_tier_model(tmp_path):
    conn = make_conn(tmp_path)
    envelope = json.dumps({"result": "hi"})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)) as mock_run:
        router.call_model(conn, "prompt", purpose="task2", routing_policy=FIXTURE_POLICY)
    args = mock_run.call_args[0][0]
    assert "model-b" in args


def test_call_model_raises_on_nonzero_exit(tmp_path):
    conn = make_conn(tmp_path)
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(1, "", "boom")):
        with pytest.raises(router.HeadlessCallFailed):
            router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY)


def test_call_model_timeout_raises(tmp_path):
    import subprocess
    conn = make_conn(tmp_path)
    with patch("harness_core.router.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=1)):
        with pytest.raises(router.HeadlessCallFailed):
            router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY)


def test_call_model_quota_like_error_flagged(tmp_path):
    conn = make_conn(tmp_path)
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(1, "", "429 rate limit exceeded")):
        with pytest.raises(router.HeadlessCallFailed) as exc_info:
            router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY)
    assert exc_info.value.likely_quota_exhausted is True


def test_claude_cli_subprocess_env_is_scrubbed_not_inherited(tmp_path, monkeypatch):
    """The claude_cli subprocess must never see the full parent environment -- it
    routinely processes untrusted context, so an arbitrary secret set in the parent
    process for unrelated reasons must not leak into it."""
    conn = make_conn(tmp_path)
    monkeypatch.setenv("A_TOTALLY_UNRELATED_SECRET", "sk-should-not-leak")
    envelope = json.dumps({"result": "hi"})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)) as mock_run:
        router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY)
    env = mock_run.call_args.kwargs["env"]
    assert "A_TOTALLY_UNRELATED_SECRET" not in env
    assert env["PATH"] == os.environ["PATH"]
    assert env["DISABLE_AUTOUPDATER"] == "1"
    assert env["DISABLE_TELEMETRY"] == "1"


def test_claude_cli_provider_extra_env_is_added_not_a_bypass():
    provider = router.ClaudeCLIProvider(extra_env={"MY_PROJECT_FLAG": "1"})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, json.dumps({"result": "hi"}))) as mock_run:
        provider.complete("prompt", "model-a", None, 30)
    env = mock_run.call_args.kwargs["env"]
    assert env["MY_PROJECT_FLAG"] == "1"
    assert env["PATH"] == os.environ["PATH"]


def test_cli_provider_defaults_to_lean_flags(tmp_path):
    conn = make_conn(tmp_path)
    envelope = json.dumps({"result": "hi"})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)) as mock_run:
        router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY)
    args = mock_run.call_args[0][0]
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--setting-sources") + 1] == ""
    assert args[args.index("--system-prompt") + 1] == router.LEAN_SYSTEM_PROMPT
    assert "--strict-mcp-config" in args and "--disable-slash-commands" in args
    assert args[-1] == "prompt"


def test_explicit_extra_flags_replace_lean_default(tmp_path):
    conn = make_conn(tmp_path)
    envelope = json.dumps({"result": "hi"})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)) as mock_run:
        router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY, extra_flags=[])
    args = mock_run.call_args[0][0]
    assert "--tools" not in args and "--system-prompt" not in args


def test_cache_conn_hit_skips_model_call_and_ledger(tmp_path):
    from harness_core import cache
    conn = make_conn(tmp_path)
    cache_conn = cache.get_connection(tmp_path / "cache.db")
    envelope = json.dumps({"result": "hi"})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)) as mock_run:
        first = router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY, cache_conn=cache_conn)
        second = router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY, cache_conn=cache_conn)
    assert first == second == "hi"
    assert mock_run.call_count == 1
    assert conn.execute("SELECT COUNT(*) FROM headless_calls").fetchone()[0] == 1


def test_cache_conn_misses_on_different_route_or_schema(tmp_path):
    from harness_core import cache
    conn = make_conn(tmp_path)
    cache_conn = cache.get_connection(tmp_path / "cache.db")
    envelope = json.dumps({"result": "hi"})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)) as mock_run:
        router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY, cache_conn=cache_conn)
        router.call_model(conn, "prompt", purpose="task2", routing_policy=FIXTURE_POLICY, cache_conn=cache_conn)
        router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY, cache_conn=cache_conn,
                          json_schema={"type": "object"})
    assert mock_run.call_count == 3


def test_cache_conn_never_stores_a_failure(tmp_path):
    from harness_core import cache
    conn = make_conn(tmp_path)
    cache_conn = cache.get_connection(tmp_path / "cache.db")
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(1, "", "boom")):
        with pytest.raises(router.HeadlessCallFailed):
            router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY, cache_conn=cache_conn)
    assert cache_conn.execute("SELECT COUNT(*) FROM cache_entries").fetchone()[0] == 0


SCHEMA_OBJ = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}


def test_prompt_mode_puts_schema_in_prompt_not_cli_flag(tmp_path):
    conn = make_conn(tmp_path)
    provider = router.ClaudeCLIProvider(structured_output="prompt")
    envelope = json.dumps({"result": '{"a": "x"}', "num_turns": 1})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)) as mock_run:
        out = router.call_model(conn, "prompt", purpose="task1", routing_policy=FIXTURE_POLICY,
                                json_schema=SCHEMA_OBJ, providers={"claude_cli": provider})
    args = mock_run.call_args[0][0]
    assert "--json-schema" not in args
    assert args[-1].startswith("prompt") and '"required": ["a"]' in args[-1]
    assert json.loads(out) == {"a": "x"}


def test_prompt_mode_strips_a_code_fence(tmp_path):
    conn = make_conn(tmp_path)
    provider = router.ClaudeCLIProvider(structured_output="prompt")
    envelope = json.dumps({"result": '```json\n{"a": "x"}\n```'})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)):
        out = router.call_model(conn, "p", purpose="task1", routing_policy=FIXTURE_POLICY,
                                json_schema=SCHEMA_OBJ, providers={"claude_cli": provider})
    assert json.loads(out) == {"a": "x"}


@pytest.mark.parametrize("result", ["not json at all", '["a"]', '{"b": "no required key"}'])
def test_prompt_mode_fails_loudly_on_malformed_answer_and_records_usage(tmp_path, result):
    conn = make_conn(tmp_path)
    provider = router.ClaudeCLIProvider(structured_output="prompt")
    envelope = json.dumps({"result": result, "num_turns": 1, "usage": {"input_tokens": 5, "output_tokens": 3}})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)) as mock_run:
        with pytest.raises(router.HeadlessCallFailed, match="prompt mode"):
            router.call_model(conn, "p", purpose="task1", routing_policy=FIXTURE_POLICY,
                              json_schema=SCHEMA_OBJ, providers={"claude_cli": provider})
    assert mock_run.call_count == 1  # never retried
    row = conn.execute("SELECT success, input_tokens, num_turns FROM headless_calls").fetchone()
    assert row["success"] == 0 and row["input_tokens"] == 5 and row["num_turns"] == 1


def test_cli_mode_is_still_the_default(tmp_path):
    conn = make_conn(tmp_path)
    envelope = json.dumps({"result": '{"a": "x"}'})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)) as mock_run:
        router.call_model(conn, "p", purpose="task1", routing_policy=FIXTURE_POLICY, json_schema=SCHEMA_OBJ)
    assert "--json-schema" in mock_run.call_args[0][0]


def test_policy_spec_selects_prompt_mode():
    built = router.build_providers({"providers": {"claude_cli": {"type": "claude_cli", "structured_output": "prompt"}}})
    assert built["claude_cli"].structured_output == "prompt"


def test_unknown_structured_output_mode_is_a_config_error():
    with pytest.raises(router.ProviderConfigError):
        router.ClaudeCLIProvider(structured_output="sometimes")


def test_num_turns_is_recorded_in_the_ledger(tmp_path):
    conn = make_conn(tmp_path)
    envelope = json.dumps({"result": "hi", "num_turns": 5, "usage": {"input_tokens": 1, "output_tokens": 1}})
    with patch("harness_core.router.subprocess.run", return_value=_fake_completed(0, envelope)):
        router.call_model(conn, "p", purpose="task1", routing_policy=FIXTURE_POLICY)
    assert conn.execute("SELECT num_turns FROM headless_calls").fetchone()["num_turns"] == 5
    assert ledger.usage_summary(conn)[0]["max_num_turns"] == 5
