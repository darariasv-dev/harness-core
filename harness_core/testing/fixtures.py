from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from harness_core.guards import network_guard


@pytest.fixture
def offline_guard() -> Iterator[None]:
    """Blocks real network/process calls for the duration of a test -- see
    harness_core.guards.network_guard's own docstring for exactly what it does and does not
    catch. A project-specific conftest.py can extend this with its own additional patches by
    calling `network_guard()` directly instead of this fixture, and adding more
    `stack.enter_context(...)` calls on the yielded ExitStack."""
    with network_guard():
        yield


def isolate_default_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, targets: list[tuple[object, str]]) -> None:
    """For each (module, attr_name) pair, points that module-level attribute at a fresh,
    empty tmp_path location -- the pattern an offline test suite needs so a test's outcome
    never silently depends on this machine's real, gitignored persisted files. Each target
    gets its own uniquely-named (never-created) path, so accidentally sharing state between
    two unrelated defaults isn't possible."""
    for module, attr_name in targets:
        monkeypatch.setattr(module, attr_name, tmp_path / f"_unused_{attr_name}")
