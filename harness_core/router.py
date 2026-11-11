"""Single entry point for every model-touching call: `call_model` resolves which model tier
a named task ("purpose") should use from a routing policy, hands the prompt to that tier's
provider (the headless `claude -p` CLI by default; a local Ollama server or an
OpenAI-compatible endpoint via harness_core.providers), records the call in a usage ledger,
and returns the result text. Routing is resolved from a plain policy dict, not a process-wide
environment variable -- so a caller never has to choose between "one global override" and
"no control at all" over which calls escalate.

Policy `tiers` accept two shapes, both supported forever:
    tiers: {cheap: "model-id"}                                  # legacy: provider claude_cli implied
    tiers: {free: {provider: ollama, model: "qwen3:4b"}}         # provider-qualified
`providers: {name: {type: claude_cli|ollama|openai_compatible, ...}}` builds the provider
objects (see `build_providers`); a tier naming a provider that isn't configured fails the
call with HeadlessCallFailed rather than silently falling back to another backend.

`pinned_tiers` ({purpose: tier}) beats the policy's task mapping, its default_tier AND any
`tier_override` -- the mechanism a consuming project uses to hard-pin sensitive purposes to
its strong tier in code, where no policy edit or eval run can move them.

The CLI provider defaults to `LEAN_CLI_FLAGS` (no tools, a one-line system prompt, no
settings/CLAUDE.md/MCP/skills) -- a narrow generation call needs none of Claude Code's agent
scaffolding, which otherwise rides along on every call. Passing `extra_flags` explicitly
replaces the default wholesale (`[]` restores the bare CLI).

`cache_conn` (optional) makes `call_model` itself cache-checked: an identical prompt on the
identical effective route returns the stored text without a model call (and without a
ledger row -- no call happened). Only successes are stored.

A failure -- including anything that looks like a rate-limit/quota exhaustion -- is surfaced
as `HeadlessCallFailed` and never retried automatically; callers decide what to do."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness_core import cache as cache_module
from harness_core import ledger as ledger_module
from harness_core import providers as providers_module
from harness_core.providers import (  # noqa: F401  (re-exported for existing importers)
    EMPTY_USAGE,
    HeadlessCallFailed,
    HostedFreeProvider,
    OllamaProvider,
    Provider,
    ProviderConfigError,
    ProviderResult,
)

CLI_BINARY = "claude"
DEFAULT_TIMEOUT_SECONDS = 120

# Default flags for the CLI provider. Without them every call carries Claude Code's full
# agent context -- default system prompt, tool schemas, the user's CLAUDE.md files and
# auto-memory, skills. Measured 2026-09-23 on a one-line prompt: ~20,000 input tokens (cache
# creation + read) with no flags, ~14,300 with `--restricted --strict-mcp-config`, ~420 with
# these. `--tools ""` also means the call cannot run any tool at all. `--bare` is NOT used:
# it never reads OAuth, which would break subscription auth.
LEAN_SYSTEM_PROMPT = "You are a precise assistant. Follow the user's instructions exactly and answer only what is asked."
LEAN_CLI_FLAGS: tuple = (
    "--tools", "",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--setting-sources", "",
    "--system-prompt", LEAN_SYSTEM_PROMPT,
)

# The CLI subprocess gets ONLY these env vars (plus LC_* locale overrides) by default --
# never the full parent environment. A `claude -p` call in a consuming project routinely
# processes untrusted context (repository text, scraped/API data); inheriting the full
# environment would hand that subprocess whatever secrets happen to be set in the parent
# process for unrelated reasons. This allowlist is the one already proven in production by
# a real consuming project's own adapter, ported into the shared library so every consumer
# gets it by default instead of reinventing (or forgetting) it per project.
_SAFE_ENV_KEYS = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TMPDIR", "TMP", "TEMP",
        "LANG", "LANGUAGE", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
        "CLAUDE_CODE_OAUTH_TOKEN",
    }
)


def _safe_environment(extra_env: Optional[dict] = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS or k.startswith("LC_")}
    env["DISABLE_AUTOUPDATER"] = "1"
    env["DISABLE_TELEMETRY"] = "1"
    env.update(extra_env or {})
    return env

# The last-resort route for a policy that names no usable tier: the STRONG tier, on Sonnet.
# A purpose nobody has classified gets the capable model, never a silent drop to the cheapest
# one; it moves DOWN only once a `tasks:` entry backed by an agreement study says it can, and
# UP (a `top` tier) only where a policy or an in-code pin names it for that purpose.
_FALLBACK_MODEL = "claude-sonnet-5-5"
_FALLBACK_TIER = "strong"
_FALLBACK_PROVIDER = "claude_cli"

_QUOTA_ERROR_MARKERS = providers_module._QUOTA_ERROR_MARKERS


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    tier: str

    @property
    def provider_hash(self) -> str:
        """Identifies the effective backend for cache keys: same policy file, different
        provider/model actually answering -> different hash."""
        return hashlib.sha256(f"{self.provider}:{self.model}".encode()).hexdigest()


def _looks_like_quota_error(text: str) -> bool:
    return providers_module.looks_like_quota_error(text)


def _extract_result_text(stdout: str) -> str:
    """`--output-format json` wraps the answer in an envelope. Parsed defensively -- falls
    back to raw stdout if the envelope shape doesn't match."""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout
    if isinstance(envelope, dict) and "result" in envelope:
        return envelope["result"]
    return stdout


def _extract_usage(stdout: str) -> dict:
    """Parses the CLI's own provider-reported usage from the envelope, when present.
    `measured` is True only when the envelope's own `usage` object was found -- a call
    reporting `input_tokens: 0` is still measured, not estimated. `thinking_tokens` is a
    SUBSET already counted inside `output_tokens` -- kept separate, never folded back in."""
    empty = dict(EMPTY_USAGE)
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return empty
    if not isinstance(envelope, dict):
        return empty
    usage = envelope.get("usage")
    if not isinstance(usage, dict):
        return {**empty, "total_cost_usd": envelope.get("total_cost_usd"), "duration_api_ms": envelope.get("duration_api_ms"),
                "num_turns": envelope.get("num_turns")}
    output_tokens_details = usage.get("output_tokens_details")
    thinking_tokens = output_tokens_details.get("thinking_tokens") if isinstance(output_tokens_details, dict) else None
    return {
        "measured": True,
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "total_cost_usd": envelope.get("total_cost_usd"),
        "duration_api_ms": envelope.get("duration_api_ms"),
        "thinking_tokens": thinking_tokens,
        "num_turns": envelope.get("num_turns"),
    }


STRUCTURED_OUTPUT_MODES = ("cli", "prompt")
_JSON_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _with_json_instruction(prompt: str, json_schema: dict) -> str:
    return (
        f"{prompt}\n\nRespond with ONLY one JSON value that validates against the JSON Schema "
        f"below -- no prose before or after it, no code fence.\nJSON Schema: {json.dumps(json_schema)}"
    )


def _parse_prompt_mode_json(text: str, json_schema: dict) -> str:
    """Prompt-mode structured output: parse the model's plain-text answer as JSON and check
    the top-level shape (type, required keys). Full schema validation stays with the caller,
    exactly as it is for the CLI's own `--json-schema` result. Never retried here."""
    candidate = (text or "").strip()
    fenced = _JSON_FENCE.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise HeadlessCallFailed("structured output (prompt mode): response was not valid JSON") from exc
    expected = json_schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise HeadlessCallFailed("structured output (prompt mode): expected a JSON object")
        missing = [key for key in json_schema.get("required", []) if key not in value]
        if missing:
            raise HeadlessCallFailed(f"structured output (prompt mode): missing required keys {missing}")
    elif expected == "array" and not isinstance(value, list):
        raise HeadlessCallFailed("structured output (prompt mode): expected a JSON array")
    return json.dumps(value, ensure_ascii=False)


def _extract_error_text(stderr: str, stdout: str, limit: int = 1500) -> str:
    """On a non-zero exit, prefer the JSON envelope's `result` field (the actual API-side
    error message) over a raw slice of stdout/stderr. Falls back to raw stderr/stdout when
    stdout isn't a JSON envelope (e.g. the CLI itself failed to start)."""
    if stdout:
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError:
            envelope = None
        if isinstance(envelope, dict) and isinstance(envelope.get("result"), str) and envelope["result"]:
            return envelope["result"].strip()[:limit]
    return (stderr or stdout or "").strip()[:limit]


class ClaudeCLIProvider:
    """The headless `claude -p` CLI. Same argv, envelope parsing and error handling as
    before the provider abstraction -- only the ledger bookkeeping moved out to `_invoke`.
    The subprocess always gets `_safe_environment()`, never `os.environ` verbatim -- see
    that function's docstring. Pass `extra_env` for the rare case a deployment genuinely
    needs one more var visible to the CLI; it does not widen the allowlist itself.
    `extra_flags=None` means `LEAN_CLI_FLAGS`; an explicit list (even `[]`) is used verbatim.

    `structured_output` decides how a `json_schema` call gets its JSON:
    - "cli" (default): the CLI's own `--json-schema`. The model answers through a tool call the
      CLI validates; on a mismatch the CLI re-prompts inside the same call, each turn
      re-reading the whole context. Measured 2026-09-23 on long free-text fields (a role review
      with an `assessment` string): 3-6 turns per call, and in 3 of 6 calls the model finally
      gave up and emitted placeholder text ("test") that DID validate -- silently accepted.
    - "prompt": no `--json-schema`; the schema goes in the prompt and the answer is parsed and
      shape-checked here (`_parse_prompt_mode_json`). One turn; a malformed answer fails the
      call loudly instead of being retried into placeholder text. Same 6 calls: 1 turn each,
      0 placeholders, ~9x fewer input tokens."""
    name = "claude_cli"

    def __init__(self, extra_flags: Optional[list[str]] = None, name: str = "claude_cli",
                 extra_env: Optional[dict[str, str]] = None, structured_output: str = "cli"):
        if structured_output not in STRUCTURED_OUTPUT_MODES:
            raise ProviderConfigError(
                f"provider {name!r}: structured_output must be one of {STRUCTURED_OUTPUT_MODES}, got {structured_output!r}"
            )
        self.extra_flags = list(LEAN_CLI_FLAGS if extra_flags is None else extra_flags)
        self.name = name
        self.extra_env = dict(extra_env or {})
        self.structured_output = structured_output

    def __repr__(self) -> str:
        return (f"ClaudeCLIProvider(name={self.name!r}, extra_flags={self.extra_flags!r}, "
                f"structured_output={self.structured_output!r})")

    def complete(self, prompt: str, model: str, json_schema: Optional[dict], timeout_seconds: int) -> ProviderResult:
        prompt_mode = json_schema is not None and self.structured_output == "prompt"
        args = [CLI_BINARY, "-p", *self.extra_flags, "--model", model, "--output-format", "json"]
        if json_schema is not None and not prompt_mode:
            args += ["--json-schema", json.dumps(json_schema)]
        args.append(_with_json_instruction(prompt, json_schema) if prompt_mode else prompt)

        try:
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=timeout_seconds,
                env=_safe_environment(self.extra_env),
            )
        except subprocess.TimeoutExpired as exc:
            raise HeadlessCallFailed("headless call timed out") from exc
        except FileNotFoundError as exc:
            raise HeadlessCallFailed(f"{CLI_BINARY!r} binary not found on PATH") from exc

        if result.returncode != 0:
            error_text = _extract_error_text(result.stderr, result.stdout)
            failure = HeadlessCallFailed(error_text or "headless call failed", likely_quota_exhausted=_looks_like_quota_error(error_text))
            failure.usage = _extract_usage(result.stdout)  # type: ignore[attr-defined]
            failure.response_chars = len(result.stdout or "")  # type: ignore[attr-defined]
            raise failure

        text = _extract_result_text(result.stdout)
        usage = _extract_usage(result.stdout)
        if prompt_mode:
            try:
                text = _parse_prompt_mode_json(text, json_schema)
            except HeadlessCallFailed as failure:
                failure.usage = usage  # type: ignore[attr-defined]
                failure.response_chars = len(result.stdout or "")  # type: ignore[attr-defined]
                raise
        return ProviderResult(text=text, usage=usage)


def build_provider(name: str, spec: dict, extra_flags: Optional[list[str]] = None) -> Provider:
    kind = (spec or {}).get("type") or name
    if kind == "claude_cli":
        return ClaudeCLIProvider(extra_flags=extra_flags, name=name,
                                 structured_output=(spec or {}).get("structured_output", "cli"))
    if kind == "ollama":
        return OllamaProvider(
            base_url=spec.get("base_url", "http://127.0.0.1:11434"),
            num_ctx=spec.get("num_ctx", 32768), think=spec.get("think", False), name=name,
        )
    if kind == "openai_compatible":
        return HostedFreeProvider(base_url=spec.get("base_url", ""), api_key_env=spec.get("api_key_env", ""), name=name)
    raise ProviderConfigError(f"provider {name!r}: unsupported type {kind!r}")


def build_providers(routing_policy: dict, extra_flags: Optional[list[str]] = None) -> dict[str, Provider]:
    """Builds every ENABLED provider in the policy's `providers:` block (`enabled` defaults to
    true). A policy with no block gets the CLI provider alone, so legacy policies keep
    working unchanged."""
    specs = routing_policy.get("providers") or {}
    built: dict[str, Provider] = {}
    for name, spec in specs.items():
        spec = spec or {}
        if spec.get("enabled", True) is False:
            continue
        built[name] = build_provider(name, spec, extra_flags=extra_flags)
    if _FALLBACK_PROVIDER not in built:
        built[_FALLBACK_PROVIDER] = ClaudeCLIProvider(extra_flags=extra_flags)
    return built


def _tier_spec(value) -> tuple[Optional[str], Optional[str]]:
    """(provider, model) for either tier shape; (None, None) when the tier is unset."""
    if isinstance(value, dict):
        return value.get("provider") or _FALLBACK_PROVIDER, value.get("model")
    if isinstance(value, str) and value:
        return _FALLBACK_PROVIDER, value
    return None, None


def resolve_route(
    purpose: str,
    routing_policy: dict,
    tier_override: Optional[str] = None,
    pinned_tiers: Optional[dict] = None,
) -> Route:
    """A missing/malformed policy, or a `purpose` not listed in `tasks`, never blocks a call
    -- falls through to the policy's own `default_tier`, then to a hardcoded safe default
    (the strong tier on Sonnet).
    `tier_override` bypasses the purpose->tier lookup (the mechanism an agreement study uses
    to force the SAME input through multiple tiers); `pinned_tiers` beats even that."""
    tiers = routing_policy.get("tiers") or {}
    default_tier = routing_policy.get("default_tier") or _FALLBACK_TIER
    pinned = (pinned_tiers or {}).get(purpose)
    tier = pinned or tier_override or (routing_policy.get("tasks") or {}).get(purpose, default_tier)
    provider, model = _tier_spec(tiers.get(tier))
    if model is None:
        provider, model = _tier_spec(tiers.get(default_tier))
    if model is None:
        provider, model = _FALLBACK_PROVIDER, _FALLBACK_MODEL
    return Route(provider=provider or _FALLBACK_PROVIDER, model=model, tier=tier)


def _invoke(
    conn: sqlite3.Connection,
    provider: Provider,
    prompt: str,
    purpose: str,
    task_id: Optional[str],
    model: str,
    json_schema: Optional[dict],
    timeout_seconds: int,
) -> str:
    call_id = ledger_module.record_call_started(
        conn, task_id, purpose, model=model, prompt_chars=len(prompt), provider=provider.name,
    )
    try:
        result = provider.complete(prompt, model, json_schema, timeout_seconds)
    except HeadlessCallFailed as exc:
        ledger_module.record_call_finished(
            conn, call_id, success=False, error=str(exc)[:1500],
            response_chars=getattr(exc, "response_chars", None), usage=getattr(exc, "usage", None),
        )
        raise
    ledger_module.record_call_finished(conn, call_id, success=True, response_chars=len(result.text), usage=result.usage)
    return result.text


def _invoke_cli(
    conn: sqlite3.Connection,
    prompt: str,
    purpose: str,
    task_id: Optional[str],
    model: str,
    json_schema: Optional[dict],
    timeout_seconds: int,
    extra_flags: Optional[list[str]] = None,
) -> str:
    """Kept for callers that invoked the CLI path directly; now the CLI provider via `_invoke`."""
    return _invoke(conn, ClaudeCLIProvider(extra_flags=extra_flags), prompt, purpose, task_id, model, json_schema, timeout_seconds)


def load_routing_policy(path: Path) -> dict:
    """A plain dict, not a dataclass -- see harness_core.policy.load_yaml_policy for the
    generic YAML-plus-content-hash loader most callers will actually use to get this dict."""
    from harness_core.policy import load_yaml_policy
    return load_yaml_policy(path)[0]


def resolve_model(
    purpose: str,
    routing_policy: dict,
    tier_override: Optional[str] = None,
    pinned_tiers: Optional[dict] = None,
) -> tuple[str, str]:
    """Returns (model_id, tier_name) -- the pre-provider view of `resolve_route`, kept for
    every existing caller."""
    route = resolve_route(purpose, routing_policy, tier_override=tier_override, pinned_tiers=pinned_tiers)
    return route.model, route.tier


def call_model(
    conn: sqlite3.Connection,
    prompt: str,
    purpose: str,
    routing_policy: dict,
    task_id: Optional[str] = None,
    json_schema: Optional[dict] = None,
    timeout_seconds: Optional[int] = None,
    tier_override: Optional[str] = None,
    extra_flags: Optional[list[str]] = None,
    providers: Optional[dict[str, Provider]] = None,
    pinned_tiers: Optional[dict] = None,
    cache_conn: Optional[sqlite3.Connection] = None,
) -> str:
    """The one entry point every model-touching stage goes through. `purpose` is both the
    ledger's `purpose` column value AND the routing-policy task-lookup key -- one string
    names both, so a usage report and the routing policy always agree on what a given call
    was for. `providers` defaults to the policy's enabled providers (plus the CLI); a route
    naming a provider that isn't in that map fails loudly instead of using another backend.
    `cache_conn`: see the module docstring."""
    route = resolve_route(purpose, routing_policy, tier_override=tier_override, pinned_tiers=pinned_tiers)
    provider_map = providers if providers is not None else build_providers(routing_policy, extra_flags=extra_flags)
    provider = provider_map.get(route.provider)
    if provider is None:
        raise HeadlessCallFailed(
            f"provider {route.provider!r} (tier {route.tier!r}) is not configured or is disabled -- unavailable"
        )
    cache_key = None
    if cache_conn is not None:
        components = _call_cache_components(prompt, route, provider, json_schema)
        cache_key = cache_module.compute_cache_key(components)
        cached = cache_module.get_cached(cache_conn, cache_key)
        if cached is not None:
            return cached["text"]
    text = _invoke(
        conn, provider, prompt, purpose, task_id, model=route.model,
        json_schema=json_schema, timeout_seconds=timeout_seconds or DEFAULT_TIMEOUT_SECONDS,
    )
    if cache_key is not None:
        cache_module.save_cached(cache_conn, cache_key, components, {"text": text})
    return text


def _call_cache_components(prompt: str, route: Route, provider: Provider, json_schema: Optional[dict]) -> dict:
    """What `call_model(cache_conn=...)` keys on: the prompt, the effective provider+model, the
    provider's CLI flags (they change the system prompt) and the schema. Purpose and task_id
    are deliberately NOT part of it -- they label a call, not its answer."""
    return {
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "provider_hash": route.provider_hash,
        "provider_flags": list(getattr(provider, "extra_flags", None) or []),
        "structured_output": getattr(provider, "structured_output", None),
        "json_schema": json.dumps(json_schema, sort_keys=True) if json_schema is not None else None,
    }
