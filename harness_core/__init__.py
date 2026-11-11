"""harness_core: the domain-agnostic core of a headless-model pipeline harness -- tiered model
routing over pluggable providers, a composite-fingerprint result cache, a usage ledger with
measured-vs-estimated accounting, typed failure classification, a workflow lock, a
per-provider demotion/escalation rule, generic gate/evidence/eval shapes, a fixed-schema
checkpoint block, and an enforced offline guard for tests.

Boundary rule (enforced by tests/test_domain_word_grep.py): nothing in this package names a
concept from any project that consumes it. Project-specific wiring -- which purposes are
pinned, what the cache fingerprints are, what a "demotion" means -- lives in the consuming
project's thin adapter modules; `template/` shows the shape. See docs/architecture.md."""

__version__ = "0.5.0"
