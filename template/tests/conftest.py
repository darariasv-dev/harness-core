import pytest

from harness_core import demotions
from harness_core.testing.fixtures import isolate_default_paths, offline_guard  # noqa: F401

from myproject import cache as cache_module
from myproject import run as run_module


@pytest.fixture(autouse=True)
def _isolate_persisted_defaults(tmp_path, monkeypatch):
    """Every persisted default path points at an empty temp location, so no test's outcome
    depends on this machine's real, gitignored files."""
    isolate_default_paths(monkeypatch, tmp_path, [
        (cache_module, "DEFAULT_PATH"),
        (run_module, "LEDGER_PATH"),
        (demotions, "LOG_PATH"),
    ])


@pytest.fixture(autouse=True)
def _offline(offline_guard):
    """Autouse: any real network or process call in any test fails loudly."""
    yield
