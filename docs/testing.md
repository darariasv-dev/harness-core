# Testing

- **Offline by construction.** `harness_core.testing.offline_guard` (or `guards.network_guard`)
  patches sockets, urllib, smtplib, httpx and `subprocess.Popen` to raise `OfflineViolation`.
  Make it autouse in the project's `conftest.py` (the template does) and compose your own
  project entry points on the same guard scope.
- **No dependence on real local files.** `testing.isolate_default_paths(monkeypatch, tmp_path,
  [(module, "DEFAULT_PATH"), ...])` points every persisted default at an unused temp path.
- **Boundary rule.** `tests/test_domain_word_grep.py` fails if a domain word from the source
  project appears anywhere in `harness_core/`. Extend `_DOMAIN_WORDS` with your own domain's
  nouns when you contribute a module back.
- **Every bug is a test.** The lock's pid-liveness and SIGTERM tests, the demotion window
  tests, and the reference-reuse test each pin a failure that happened for real.
- Run: `pytest -q` (core), `cd template && pytest -q`, `python examples/minimal_pipeline.py`.
  CI runs all three on Python 3.9 and 3.12.
