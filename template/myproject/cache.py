"""Result cache with a FIXED, NAMED fingerprint set. Every input that can change a model
result's outcome gets its own named component, so a change to one of them invalidates
exactly the entries it should. Add a component only by appending a defaulted parameter --
the key shape never changes for existing callers, only the values do.

Components (the job-search project that produced this harness used exactly these eight):
  content_hash        the input item's text
  context_hash        the caller-supplied context given to the model (e.g. approved facts)
  exclusions_hash     things the model was told NOT to claim (confirmed gaps)
  taxonomy_hash       the classification/vocabulary file
  scoring_version     the scoring policy version
  prompt_hash         the prompt template
  routing_hash        the routing policy file's content
  provider_hash       the EFFECTIVE provider+model that answered (myproject.router)"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from harness_core import cache as harness_cache

DEFAULT_PATH = Path("data/cache/results.db")


def get_connection(path: Path = DEFAULT_PATH) -> sqlite3.Connection:
    return harness_cache.get_connection(path)


def _components(content_hash, context_hash, exclusions_hash, taxonomy_hash, scoring_version,
                prompt_hash, routing_hash, provider_hash) -> dict:
    return {
        "content_hash": content_hash, "context_hash": context_hash, "exclusions_hash": exclusions_hash,
        "taxonomy_hash": taxonomy_hash, "scoring_version": scoring_version, "prompt_hash": prompt_hash,
        "routing_hash": routing_hash, "provider_hash": provider_hash,
    }


def compute_cache_key(content_hash: str, context_hash: str = "", exclusions_hash: str = "", taxonomy_hash: str = "",
                      scoring_version: str = "", prompt_hash: str = "", routing_hash: str = "", provider_hash: str = "") -> str:
    return harness_cache.compute_cache_key(_components(
        content_hash, context_hash, exclusions_hash, taxonomy_hash, scoring_version, prompt_hash, routing_hash, provider_hash))


def get_cached(conn: sqlite3.Connection, cache_key: str) -> Optional[dict]:
    return harness_cache.get_cached(conn, cache_key)


def save(conn: sqlite3.Connection, cache_key: str, value: dict, content_hash: str, context_hash: str = "",
         exclusions_hash: str = "", taxonomy_hash: str = "", scoring_version: str = "", prompt_hash: str = "",
         routing_hash: str = "", provider_hash: str = "") -> None:
    harness_cache.save_cached(conn, cache_key, _components(
        content_hash, context_hash, exclusions_hash, taxonomy_hash, scoring_version, prompt_hash, routing_hash, provider_hash), value)
