import socket

import pytest

from harness_core.guards import OfflineViolation
from harness_core.testing import isolate_default_paths, offline_guard


def test_offline_guard_fixture_blocks_socket(offline_guard):
    with pytest.raises(OfflineViolation):
        socket.socket()


class _FakeModule:
    default_path = "/real/path/should/not/be/used.json"


def test_isolate_default_paths_points_at_tmp_path(tmp_path, monkeypatch):
    isolate_default_paths(monkeypatch, tmp_path, [(_FakeModule, "default_path")])
    assert str(tmp_path) in str(_FakeModule.default_path)
    assert not _FakeModule.default_path.exists()
