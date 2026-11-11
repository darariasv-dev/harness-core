"""Project-side wrapper over harness_core.router. Three things belong HERE, in code, not in
the policy file:

1. PINNED_STRONG -- purposes whose output a human outside the project reads (or that decide
   something irreversible) are pinned to the strong tier. No `tasks:` entry, default_tier,
   eval tier_override, or future policy edit can move them; adding a name is a code change
   with a test.
2. The CLI provider's flags: harness_core's LEAN_CLI_FLAGS (no tools, a one-line system
   prompt, no settings/CLAUDE.md/MCP/skills -- ~420 input tokens of overhead per call instead
   of ~14-20k) plus `--restricted` as defense in depth. `--restricted` alone does NOT remove
   the file tools or Claude Code's default system prompt.
3. provider_hash_for -- the EFFECTIVE provider+model for a purpose, including a runtime
   escalation, fed into the cache key so a result is never reused across backends."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from harness_core import router as harness_router
from harness_core.policy import load_yaml_policy

DEFAULT_ROUTING_POLICY_PATH = Path("policy/model_routing.v1.yaml")
_RESTRICTED_FLAGS = [*harness_router.LEAN_CLI_FLAGS, "--restricted"]
STRONG_TIER = "strong"

PINNED_STRONG = frozenset({"draft_for_human", "resolve_ambiguity"})
PINNED_TIERS = {purpose: STRONG_TIER for purpose in PINNED_STRONG}

HeadlessCallFailed = harness_router.HeadlessCallFailed
Route = harness_router.Route


def load_routing_policy(path: Path = DEFAULT_ROUTING_POLICY_PATH) -> dict:
    return load_yaml_policy(path)[0]


def routing_policy_hash(path: Path = DEFAULT_ROUTING_POLICY_PATH) -> str:
    return load_yaml_policy(path)[1]


def build_providers(routing_policy: Optional[dict] = None) -> dict:
    policy = routing_policy if routing_policy is not None else load_routing_policy()
    return harness_router.build_providers(policy, extra_flags=_RESTRICTED_FLAGS)


def resolve_route(purpose: str, routing_policy: Optional[dict] = None, tier_override: Optional[str] = None) -> Route:
    policy = routing_policy if routing_policy is not None else load_routing_policy()
    return harness_router.resolve_route(purpose, policy, tier_override=tier_override, pinned_tiers=PINNED_TIERS)


def provider_hash_for(purpose: str, routing_policy: Optional[dict] = None, tier_override: Optional[str] = None) -> str:
    return resolve_route(purpose, routing_policy, tier_override=tier_override).provider_hash


def is_pinned_strong(purpose: str) -> bool:
    return purpose in PINNED_STRONG


def call_model(conn: sqlite3.Connection, prompt: str, purpose: str, task_id: Optional[str] = None,
               json_schema: Optional[dict] = None, timeout_seconds: Optional[int] = None,
               routing_policy: Optional[dict] = None, tier_override: Optional[str] = None,
               providers: Optional[dict] = None) -> str:
    """The one entry point. `purpose` is both the ledger row's purpose and the policy's
    task-lookup key, so usage reports and the policy always agree on what a call was for."""
    policy = routing_policy if routing_policy is not None else load_routing_policy()
    provider_map = providers if providers is not None else build_providers(policy)
    return harness_router.call_model(
        conn, prompt, purpose, policy, task_id=task_id, json_schema=json_schema,
        timeout_seconds=timeout_seconds, tier_override=tier_override,
        extra_flags=_RESTRICTED_FLAGS, providers=provider_map, pinned_tiers=PINNED_TIERS,
    )
