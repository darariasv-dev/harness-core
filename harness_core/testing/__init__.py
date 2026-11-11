"""Shipped test-support utilities for a project built on harness-core: a pytest fixture
wrapping harness_core.guards.network_guard, and a small helper for the "point every
persisted-default-path module attribute at an empty tmp_path location" pattern an offline
test suite needs so its outcome never silently depends on whatever this machine's real,
gitignored data files happen to contain."""
from harness_core.testing.fixtures import isolate_default_paths, offline_guard

__all__ = ["offline_guard", "isolate_default_paths"]
