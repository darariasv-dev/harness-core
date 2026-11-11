"""harness_core.providers + the provider-aware router: offline only (httpx and subprocess are
mocked). Covers the two properties the user's spec makes non-negotiable -- a local provider
is loopback-only, and a hosted provider's key never appears anywhere observable."""
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from harness_core import env, ledger, providers, router
from harness_core.failures import FailureClass, classify_headless_failure


def _response(status_code=200, body=None, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = text or (json.dumps(body) if body is not None else "")
    return resp


# --- Ollama -------------------------------------------------------------------------------

def test_ollama_request_carries_num_ctx_schema_and_think_false():
    provider = providers.OllamaProvider(base_url="http://127.0.0.1:11434", num_ctx=32768, think=False)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    body = {"message": {"content": '{"ok": true}'}, "prompt_eval_count": 27000, "eval_count": 400, "total_duration": 95_000_000_000}
    with patch("harness_core.providers.httpx.post", return_value=_response(200, body)) as mock_post:
        result = provider.complete("prompt", "qwen3:4b", schema, timeout_seconds=600)
    kwargs = mock_post.call_args.kwargs
    assert mock_post.call_args.args[0] == "http://127.0.0.1:11434/api/chat"
    payload = kwargs["json"]
    assert payload["model"] == "qwen3:4b"
    assert payload["options"]["num_ctx"] == 32768
    assert payload["options"]["temperature"] == 0
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["format"] == schema
    assert kwargs["timeout"] == 600
    assert result.text == '{"ok": true}'
    assert result.usage["measured"] is True
    assert result.usage["input_tokens"] == 27000 and result.usage["output_tokens"] == 400
    assert result.usage["duration_api_ms"] == 95000
    assert result.usage["total_cost_usd"] == 0.0


def test_ollama_omits_format_when_no_schema():
    provider = providers.OllamaProvider()
    assert "format" not in provider.build_payload("p", "m", None)


@pytest.mark.parametrize("url", ["http://ollama.example.com:11434", "http://10.0.0.5:11434", "https://api.ollama.com"])
def test_ollama_refuses_a_non_loopback_base_url(url):
    with pytest.raises(providers.ProviderConfigError):
        providers.OllamaProvider(base_url=url)


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434/"])
def test_ollama_accepts_loopback(url):
    assert providers.OllamaProvider(base_url=url).base_url.startswith("http://")


def test_ollama_connection_error_classifies_as_unavailable_with_a_start_hint():
    provider = providers.OllamaProvider()
    with patch("harness_core.providers.httpx.post", side_effect=httpx.ConnectError("refused")):
        with pytest.raises(providers.HeadlessCallFailed) as exc_info:
            provider.complete("p", "m", None, 10)
    assert classify_headless_failure(exc_info.value) is FailureClass.UNAVAILABLE
    assert "ollama serve" in str(exc_info.value)


def test_ollama_timeout_classifies_as_timeout():
    provider = providers.OllamaProvider()
    with patch("harness_core.providers.httpx.post", side_effect=httpx.ReadTimeout("slow")):
        with pytest.raises(providers.HeadlessCallFailed) as exc_info:
            provider.complete("p", "m", None, 10)
    assert classify_headless_failure(exc_info.value) is FailureClass.TIMEOUT


def test_ollama_http_error_surfaces_status_and_body():
    provider = providers.OllamaProvider()
    with patch("harness_core.providers.httpx.post", return_value=_response(500, None, text="model not found")):
        with pytest.raises(providers.HeadlessCallFailed) as exc_info:
            provider.complete("p", "m", None, 10)
    assert "500" in str(exc_info.value) and "model not found" in str(exc_info.value)


def test_ollama_is_available_probe():
    provider = providers.OllamaProvider()
    with patch("harness_core.providers.httpx.get", return_value=_response(200, {"models": []})):
        assert provider.is_available() is True
    with patch("harness_core.providers.httpx.get", side_effect=httpx.ConnectError("refused")):
        assert provider.is_available() is False


# --- Hosted (OpenAI-compatible) -------------------------------------------------------------

def test_hosted_key_comes_from_dotenv_and_never_appears_in_repr(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_HOSTED_KEY", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text('# comment\nexport TEST_HOSTED_KEY="sk-secret-value-123"\n')
    provider = providers.HostedFreeProvider("https://free.example/v1", "TEST_HOSTED_KEY", name="hosted_free", dotenv_path=dotenv)
    assert "sk-secret-value-123" not in repr(provider)
    assert "TEST_HOSTED_KEY" in repr(provider)
    body = {"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
    with patch("harness_core.providers.httpx.post", return_value=_response(200, body)) as mock_post:
        result = provider.complete("p", "some-model", {"type": "object"}, 30)
    kwargs = mock_post.call_args.kwargs
    assert kwargs["headers"]["Authorization"] == "Bearer sk-secret-value-123"
    assert kwargs["json"]["response_format"]["type"] == "json_schema"
    assert result.usage["input_tokens"] == 5 and result.usage["measured"] is True


def test_hosted_missing_key_names_the_variable_not_a_value(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_HOSTED_KEY", raising=False)
    with pytest.raises(providers.ProviderConfigError) as exc_info:
        providers.HostedFreeProvider("https://free.example/v1", "TEST_HOSTED_KEY", dotenv_path=tmp_path / ".env")
    assert "TEST_HOSTED_KEY" in str(exc_info.value)


def test_hosted_requires_a_base_url(monkeypatch):
    monkeypatch.setenv("TEST_HOSTED_KEY", "x")
    with pytest.raises(providers.ProviderConfigError):
        providers.HostedFreeProvider("", "TEST_HOSTED_KEY")


def test_hosted_429_is_flagged_quota_like(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_HOSTED_KEY", "k")
    provider = providers.HostedFreeProvider("https://free.example/v1", "TEST_HOSTED_KEY")
    with patch("harness_core.providers.httpx.post", return_value=_response(429, None, text="slow down")):
        with pytest.raises(providers.HeadlessCallFailed) as exc_info:
            provider.complete("p", "m", None, 10)
    assert exc_info.value.likely_quota_exhausted is True


def test_read_env_var_prefers_environment_over_dotenv(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("K=from_file\n")
    assert env.read_env_var("K", dotenv_path=dotenv) == "from_file"
    monkeypatch.setenv("K", "from_env")
    assert env.read_env_var("K", dotenv_path=dotenv) == "from_env"
    assert env.read_env_var("MISSING", dotenv_path=dotenv) is None


# --- Router: provider-qualified tiers, pins, provider column ---------------------------------

PROVIDER_POLICY = {
    "providers": {
        "claude_cli": {"type": "claude_cli"},
        "ollama": {"type": "ollama", "base_url": "http://127.0.0.1:11434", "num_ctx": 32768},
        "hosted_free": {"type": "openai_compatible", "base_url": "", "api_key_env": "NOPE", "enabled": False},
    },
    "tiers": {
        "free": {"provider": "ollama", "model": "qwen3:4b"},
        "cheap": {"provider": "claude_cli", "model": "model-a"},
        "strong": {"provider": "claude_cli", "model": "model-b"},
    },
    "tasks": {"task1": "free", "task2": "strong", "pinned": "free"},
    "default_tier": "cheap",
}
LEGACY_POLICY = {"tiers": {"cheap": "model-a", "strong": "model-b"}, "tasks": {"task1": "cheap"}, "default_tier": "cheap"}


def test_resolve_route_reads_provider_qualified_tiers():
    route = router.resolve_route("task1", PROVIDER_POLICY)
    assert (route.provider, route.model, route.tier) == ("ollama", "qwen3:4b", "free")
    assert router.resolve_model("task1", PROVIDER_POLICY) == ("qwen3:4b", "free")


def test_resolve_route_legacy_string_tiers_imply_claude_cli():
    route = router.resolve_route("task1", LEGACY_POLICY)
    assert (route.provider, route.model, route.tier) == ("claude_cli", "model-a", "cheap")
    assert router.resolve_route("unknown", LEGACY_POLICY).provider == "claude_cli"


def test_pinned_tiers_beat_task_mapping_default_and_override():
    pins = {"pinned": "strong"}
    assert router.resolve_route("pinned", PROVIDER_POLICY, pinned_tiers=pins).tier == "strong"
    assert router.resolve_route("pinned", PROVIDER_POLICY, tier_override="free", pinned_tiers=pins).tier == "strong"
    assert router.resolve_route("task1", PROVIDER_POLICY, tier_override="free", pinned_tiers=pins).tier == "free"


def test_provider_hash_changes_with_provider_or_model():
    a = router.Route("ollama", "qwen3:4b", "free").provider_hash
    b = router.Route("claude_cli", "qwen3:4b", "free").provider_hash
    c = router.Route("ollama", "qwen2.5:7b", "free").provider_hash
    assert len({a, b, c}) == 3
    assert router.Route("ollama", "qwen3:4b", "other-tier-name").provider_hash == a


def test_build_providers_skips_disabled_and_always_includes_cli():
    built = router.build_providers(PROVIDER_POLICY, extra_flags=["--x"])
    assert set(built) == {"claude_cli", "ollama"}
    assert built["claude_cli"].extra_flags == ["--x"]
    assert set(router.build_providers(LEGACY_POLICY)) == {"claude_cli"}


def test_call_model_routes_to_the_named_provider_and_records_it(tmp_path):
    conn = ledger.get_connection(tmp_path / "ledger.db")
    fake = MagicMock()
    fake.name = "ollama"
    fake.complete.return_value = providers.ProviderResult(text='{"v": 1}', usage={**providers.EMPTY_USAGE, "measured": True, "input_tokens": 3, "output_tokens": 1})
    text = router.call_model(conn, "prompt", purpose="task1", routing_policy=PROVIDER_POLICY, providers={"ollama": fake, "claude_cli": MagicMock()})
    assert text == '{"v": 1}'
    fake.complete.assert_called_once_with("prompt", "qwen3:4b", None, router.DEFAULT_TIMEOUT_SECONDS)
    row = conn.execute("SELECT provider, model, purpose, success, input_tokens FROM headless_calls").fetchone()
    assert (row["provider"], row["model"], row["purpose"], row["success"], row["input_tokens"]) == ("ollama", "qwen3:4b", "task1", 1, 3)


def test_call_model_fails_loudly_when_the_routed_provider_is_missing(tmp_path):
    conn = ledger.get_connection(tmp_path / "ledger.db")
    with pytest.raises(router.HeadlessCallFailed) as exc_info:
        router.call_model(conn, "prompt", purpose="task1", routing_policy=PROVIDER_POLICY, providers={"claude_cli": MagicMock()})
    assert "ollama" in str(exc_info.value)
    assert classify_headless_failure(exc_info.value) is FailureClass.UNAVAILABLE


def test_call_model_records_a_provider_failure_in_the_ledger(tmp_path):
    conn = ledger.get_connection(tmp_path / "ledger.db")
    fake = MagicMock()
    fake.name = "ollama"
    fake.complete.side_effect = providers.HeadlessCallFailed("ollama call timed out after 10s")
    with pytest.raises(router.HeadlessCallFailed):
        router.call_model(conn, "prompt", purpose="task1", routing_policy=PROVIDER_POLICY, providers={"ollama": fake})
    row = conn.execute("SELECT provider, success, error FROM headless_calls").fetchone()
    assert row["provider"] == "ollama" and row["success"] == 0 and "timed out" in row["error"]


def test_usage_by_provider_groups_rows(tmp_path):
    conn = ledger.get_connection(tmp_path / "ledger.db")
    for provider_name, model in (("ollama", "qwen3:4b"), ("ollama", "qwen3:4b"), ("claude_cli", "model-b")):
        call_id = ledger.record_call_started(conn, None, "task1", model=model, prompt_chars=10, provider=provider_name)
        ledger.record_call_finished(conn, call_id, success=True, response_chars=5, usage={**providers.EMPTY_USAGE, "measured": True, "input_tokens": 2, "output_tokens": 1, "duration_api_ms": 100})
    rows = {(r["provider"], r["model"]): r for r in ledger.usage_by_provider(conn)}
    assert rows[("ollama", "qwen3:4b")]["call_count"] == 2
    assert rows[("ollama", "qwen3:4b")]["measured_input_tokens"] == 4
    assert rows[("claude_cli", "model-b")]["measured_duration_ms"] == 100


def test_get_connection_adds_the_provider_column_to_an_older_ledger(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE headless_calls (id TEXT PRIMARY KEY, task_id TEXT, purpose TEXT NOT NULL, success INTEGER, error TEXT, started_at TEXT NOT NULL, finished_at TEXT, model TEXT, prompt_chars INTEGER, response_chars INTEGER, input_tokens INTEGER, output_tokens INTEGER, cache_creation_input_tokens INTEGER, cache_read_input_tokens INTEGER, total_cost_usd REAL, duration_api_ms INTEGER, usage_source TEXT, thinking_tokens INTEGER)")
    old.commit(); old.close()
    conn = ledger.get_connection(path)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(headless_calls)")}
    assert "provider" in columns
