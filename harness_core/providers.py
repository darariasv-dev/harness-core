"""Model providers behind harness_core.router: a `Provider` turns (prompt, model, schema) into
text plus a usage dict in the exact shape harness_core.ledger.record_call_finished accepts.
The router decides WHICH provider/model a purpose gets (policy `tiers`); a provider only
knows HOW to call one backend. Every failure surfaces as `HeadlessCallFailed` (defined here,
re-exported by harness_core.router so existing `router.HeadlessCallFailed` imports keep
working), with "timed out" / `likely_quota_exhausted` / "unavailable" wording that
harness_core.failures.classify_headless_failure already understands.

Providers here:
- `OllamaProvider` -- a local Ollama server, LOOPBACK ONLY (a non-loopback base_url is
  refused at construction). Sends `format=<json schema>` for structured output, sets
  `num_ctx` explicitly (Ollama's default 4,096 would silently truncate a long prompt), and
  `think=false` by default.
- `HostedFreeProvider` -- an OpenAI-compatible chat endpoint. Off unless a policy enables
  it. Its API key is read via harness_core.env.read_env_var (environment, then `.env`) and
  is never logged, never in `__repr__`, never written to the ledger (only the provider NAME
  is recorded there).

The `claude -p` CLI provider lives in harness_core.router itself (its subprocess mechanics
were already there and are patched by that module's name in tests)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional, Protocol
from urllib.parse import urlparse

import httpx

from harness_core.env import read_env_var

_QUOTA_ERROR_MARKERS = ("rate limit", "quota", "usage limit", "429")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

EMPTY_USAGE: dict = {
    "measured": False, "input_tokens": None, "output_tokens": None,
    "cache_creation_input_tokens": None, "cache_read_input_tokens": None,
    "total_cost_usd": None, "duration_api_ms": None, "thinking_tokens": None, "num_turns": None,
}


class HeadlessCallFailed(Exception):
    def __init__(self, message: str, likely_quota_exhausted: bool = False):
        super().__init__(message)
        self.likely_quota_exhausted = likely_quota_exhausted


class ProviderConfigError(ValueError):
    """A provider cannot be built from its spec (unsupported type, missing key, unsafe URL).
    Messages name the offending setting, never a secret's value."""


def looks_like_quota_error(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _QUOTA_ERROR_MARKERS)


@dataclass
class ProviderResult:
    text: str
    usage: dict = field(default_factory=lambda: dict(EMPTY_USAGE))


class Provider(Protocol):
    name: str

    def complete(self, prompt: str, model: str, json_schema: Optional[dict], timeout_seconds: int) -> ProviderResult: ...


def _require_loopback(base_url: str) -> str:
    host = urlparse(base_url).hostname
    if host not in _LOOPBACK_HOSTS:
        raise ProviderConfigError(
            f"ollama base_url must be loopback (127.0.0.1 / localhost), got host {host!r} -- "
            "a local provider is never pointed at a remote host"
        )
    return base_url.rstrip("/")


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str = "http://127.0.0.1:11434", num_ctx: int = 32768, think: bool = False, name: str = "ollama"):
        self.base_url = _require_loopback(base_url)
        self.num_ctx = int(num_ctx)
        self.think = bool(think)
        self.name = name

    def __repr__(self) -> str:
        return f"OllamaProvider(name={self.name!r}, base_url={self.base_url!r}, num_ctx={self.num_ctx}, think={self.think})"

    def start_hint(self) -> str:
        return ("start it with: OLLAMA_NO_CLOUD=true OLLAMA_HOST=127.0.0.1:11434 ollama serve "
                "(binary at /Applications/Ollama.app/Contents/Resources/ollama if not on PATH)")

    def is_available(self, timeout_seconds: float = 2.0) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=timeout_seconds)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def build_payload(self, prompt: str, model: str, json_schema: Optional[dict]) -> dict:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": self.think,
            "options": {"num_ctx": self.num_ctx, "temperature": 0},
        }
        if json_schema is not None:
            payload["format"] = json_schema
        return payload

    def complete(self, prompt: str, model: str, json_schema: Optional[dict], timeout_seconds: int) -> ProviderResult:
        payload = self.build_payload(prompt, model, json_schema)
        try:
            response = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout_seconds)
        except httpx.TimeoutException as exc:
            raise HeadlessCallFailed(f"ollama call timed out after {timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise HeadlessCallFailed(f"ollama unavailable at {self.base_url} -- {self.start_hint()}") from exc
        if response.status_code != 200:
            error_text = (response.text or "").strip()[:1500]
            raise HeadlessCallFailed(
                f"ollama returned HTTP {response.status_code}: {error_text}",
                likely_quota_exhausted=looks_like_quota_error(error_text),
            )
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise HeadlessCallFailed("ollama returned a non-JSON body") from exc
        message = body.get("message") if isinstance(body, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise HeadlessCallFailed("ollama response had no message.content")
        total_ns = body.get("total_duration")
        usage = {
            **EMPTY_USAGE,
            "measured": True,
            "input_tokens": body.get("prompt_eval_count"),
            "output_tokens": body.get("eval_count"),
            "total_cost_usd": 0.0,
            "duration_api_ms": int(total_ns / 1_000_000) if isinstance(total_ns, (int, float)) else None,
        }
        return ProviderResult(text=text, usage=usage)


class HostedFreeProvider:
    """OpenAI-compatible chat completions. The key is looked up once at construction and kept
    only as a private attribute used for the Authorization header."""

    def __init__(self, base_url: str, api_key_env: str, name: str = "hosted_free", dotenv_path=None):
        if not base_url:
            raise ProviderConfigError(f"hosted provider {name!r} has no base_url configured")
        key = read_env_var(api_key_env, dotenv_path=dotenv_path)
        if not key:
            raise ProviderConfigError(
                f"hosted provider {name!r}: {api_key_env} is not set (checked the environment and .env)"
            )
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key_env = api_key_env
        self._api_key = key

    def __repr__(self) -> str:
        return f"HostedFreeProvider(name={self.name!r}, base_url={self.base_url!r}, api_key_env={self.api_key_env!r})"

    def build_payload(self, prompt: str, model: str, json_schema: Optional[dict]) -> dict:
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
        if json_schema is not None:
            payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "response", "schema": json_schema}}
        return payload

    def complete(self, prompt: str, model: str, json_schema: Optional[dict], timeout_seconds: int) -> ProviderResult:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions", json=self.build_payload(prompt, model, json_schema),
                headers=headers, timeout=timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise HeadlessCallFailed(f"{self.name} call timed out after {timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise HeadlessCallFailed(f"{self.name} unavailable at {self.base_url}") from exc
        if response.status_code != 200:
            error_text = (response.text or "").strip()[:1500]
            raise HeadlessCallFailed(
                f"{self.name} returned HTTP {response.status_code}: {error_text}",
                likely_quota_exhausted=response.status_code == 429 or looks_like_quota_error(error_text),
            )
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise HeadlessCallFailed(f"{self.name} returned a non-JSON body") from exc
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise HeadlessCallFailed(f"{self.name} response had no choices[0].message.content") from exc
        usage_obj = body.get("usage") if isinstance(body, dict) else None
        usage = dict(EMPTY_USAGE)
        if isinstance(usage_obj, dict):
            usage.update({
                "measured": True,
                "input_tokens": usage_obj.get("prompt_tokens"),
                "output_tokens": usage_obj.get("completion_tokens"),
                "total_cost_usd": 0.0,
            })
        return ProviderResult(text=text, usage=usage)
