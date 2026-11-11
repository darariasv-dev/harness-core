# CLAUDE.md — working in harness-core

This repo is a library (`harness_core`) plus a starter project (`template/`). Resuming?
Read `README.md`, then `docs/architecture.md`. To start a NEW project on this harness, copy
`template/` and follow `docs/adopting.md`; `template/CLAUDE.md` becomes that project's own.

**Every live model call in a project built on this harness goes through `harness_core.router`,**
via a thin per-project `router.py`/`cache.py` wrapper (see `docs/adopting.md` and
`template/myproject/router.py` for the pattern) -- never a direct `claude -p` subprocess call.
Adopt it from a project's first live call, not as a retrofit.

## Non-negotiable boundaries

- **No domain words in `harness_core/`.** `tests/test_domain_word_grep.py` enforces the list.
  A symbol that needs a domain noun belongs in a consuming project's adapter.
- **No paid API paths, no retries into rate limits, no invented quota figures.** A
  `HeadlessCallFailed` with `likely_quota_exhausted` stops the caller; it is never retried here.
- **Secrets are read via `env.read_env_var` and never logged, never in `__repr__`, never in
  the ledger.** Only a provider's NAME is recorded.
- **Ollama is loopback only.** `OllamaProvider` refuses any other host at construction.
- **The `claude_cli` subprocess never inherits the full parent environment.**
  `router._safe_environment` allowlists it; a consuming project adds to the allowlist via
  `ClaudeCLIProvider(extra_env=...)`, never by passing `os.environ` through directly.
- **Tests are offline.** The guard is autouse in `template/`; the core tests use the
  `offline_guard` fixture wherever a call could reach out.
- **Every bug fix ships with a test that would have caught it.**

## Commands

```
pip install -e ".[test]" && pytest -q
pip install -e template && (cd template && pytest -q)
python examples/minimal_pipeline.py --run-dir /tmp/example-run
```

## Adding a module

Write the docstring first stating what the module owns and what it never knows (see any
existing module). Run the domain-word test before adding content. Keep persisted default
paths as module attributes so `testing.isolate_default_paths` can redirect them.

## Versioning

`harness_core.__version__` and `pyproject.toml` move together. The cache key SHAPE
(`cache.compute_cache_key` over an ordered dict) and the ledger columns are contracts;
add columns via `ledger._LATER_COLUMNS`, never by editing `_SCHEMA` alone.

A change to the cache key SHAPE or to the ledger columns is a MINOR bump at minimum,
never a patch. Consumers pin `>=X.Y.Z,<X.(Y+1).0`, so a minor bump is a deliberate,
reviewed adoption in each consumer, not a silent upgrade.
