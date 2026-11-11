# CLAUDE.md — working in Harness_Pipeline

This repo is a library (`harness_core`) plus a starter project (`template/`). Resuming?
Read `README.md`, then `docs/architecture.md`. To start a NEW project on this harness, copy
`template/` and follow `docs/adopting.md`; `template/CLAUDE.md` becomes that project's own.

**This is the mandatory routing point for every live Claude call in every project this user
builds — standing instruction from the project owner, not specific to any one project.** No
project should ever shell out to `claude -p` directly; it goes through `harness_core.router`
(this package) instead, via a thin per-project `router.py`/`cache.py` wrapper (see
`docs/adopting.md` and `template/myproject/router.py` for the pattern). Opportunity-Engine
(`agents/router.py`, gap 0028) and C-Suite-Agents/Mission Control (`mission_control/router.py`)
already follow it; any new project should from the start, not retrofitted later.

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
reviewed adoption in each consumer, not a silent upgrade (blueprint G-17).

## Standing instruction — status reviews and remediation reviews

When the owner asks any form of **"where are we / what have we done / why are there so many
failures / how do these repos connect?"**, follow
[`docs/cross_repo_review_playbook.md`](docs/cross_repo_review_playbook.md) in `Harness_Pipeline` — a standing
instruction from the project owner, applying to every project, not specific to this one.

Two parts, and **Part A is never the finished deliverable**: Part A is the state-of-play
review (inventory → read the durable records → **verify, do not relay** → categorize by
failure pattern → report in plain PM English). Part B is the 10-field remediation review
(gap / why it matters / current state / target state / required fix / updated version /
optimization / dependencies / priority / acceptance criteria), plus cross-gap analysis,
prioritized plan, optimized end state, remaining risks and a final validation checklist.
**Unless told otherwise, always continue from Part A into Part B.**

Two hard rules: never assume something is fixed without evidence — a gap doc marked FIXED is
a claim to re-verify against the code, not a fact; and label anything unknown
**"Needs validation"** rather than inventing an answer. Always separate "I verified this"
from "the record claims this."
