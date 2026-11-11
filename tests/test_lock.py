"""WorkflowLock: session takeover rules, pid-liveness staleness, and SIGTERM release."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from harness_core.lock import LockHeldByAnotherSession, WorkflowLock, _pid_alive

ROOT = str(Path(__file__).parent.parent)


def make_lock(tmp_path):
    return WorkflowLock(path=tmp_path / ".workflow.lock")


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _write_lock(path: Path, pid: int, age_seconds: float = 0.0) -> None:
    path.write_text(json.dumps({"session_id": "other-session", "pid": pid, "paths": [], "acquired_at": time.time() - age_seconds}))


def test_acquire_and_release_round_trip(tmp_path):
    lock = make_lock(tmp_path)
    lock.acquire("session-a")
    assert lock.is_held() is True
    lock.release("session-a")
    assert lock.is_held() is False


def test_second_session_refused_while_held(tmp_path):
    lock = make_lock(tmp_path)
    lock.acquire("session-a")
    try:
        make_lock(tmp_path).acquire("session-b")
        assert False, "expected LockHeldByAnotherSession"
    except LockHeldByAnotherSession as exc:
        assert exc.holder["session_id"] == "session-a"


def test_same_session_can_reacquire_and_wrong_session_cannot_release(tmp_path):
    lock = make_lock(tmp_path)
    lock.acquire("session-a")
    lock.acquire("session-a")
    lock.release("session-b")
    assert lock.is_held() is True


def test_time_stale_lock_is_taken_over(tmp_path):
    lock = make_lock(tmp_path)
    lock.acquire("session-a")
    data = json.loads(lock.path.read_text()); data["acquired_at"] = time.time() - 31 * 60
    lock.path.write_text(json.dumps(data))
    other = make_lock(tmp_path); other.acquire("session-b")
    assert other.is_held() is True


def test_pid_alive_probe():
    assert _pid_alive(os.getpid()) is True
    assert _pid_alive(_dead_pid()) is False


def test_lock_held_by_a_dead_pid_is_stale_immediately(tmp_path):
    lock = make_lock(tmp_path)
    _write_lock(lock.path, _dead_pid(), age_seconds=5)
    assert lock.is_held() is False
    lock.acquire("session-b")
    assert json.loads(lock.path.read_text())["session_id"] == "session-b"


def test_live_pid_is_refused_until_the_time_limit(tmp_path):
    lock = make_lock(tmp_path)
    _write_lock(lock.path, os.getpid(), age_seconds=5)
    assert lock.is_held() is True
    _write_lock(lock.path, os.getpid(), age_seconds=31 * 60)
    assert lock.is_held() is False


def test_clear_if_stale_removes_only_a_stale_lock(tmp_path):
    lock = make_lock(tmp_path)
    assert lock.clear_if_stale() is None
    _write_lock(lock.path, os.getpid())
    assert lock.clear_if_stale() is None and lock.path.exists()
    dead = _dead_pid(); _write_lock(lock.path, dead)
    assert lock.clear_if_stale()["pid"] == dead and not lock.path.exists()


def test_concurrent_acquire_on_an_unheld_lock_never_double_succeeds(tmp_path):
    """A plain read-then-write acquire has a TOCTOU window: two threads can both read "no
    lock exists" before either writes one, and both believe they hold it. Drives many
    racing acquire attempts (one winner session, several distinct losing sessions) at the
    same fresh lock path and asserts exactly one session ends up as the recorded holder --
    proving the exclusive-create fast path actually serializes them."""
    path = tmp_path / ".workflow.lock"
    winners = []
    lock_errors = []
    barrier = threading.Barrier(8)

    def attempt(session_id):
        barrier.wait()
        lock = WorkflowLock(path=path)
        try:
            lock.acquire(session_id)
            winners.append(session_id)
        except LockHeldByAnotherSession:
            lock_errors.append(session_id)

    threads = [threading.Thread(target=attempt, args=(f"session-{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(winners) == 1, f"expected exactly one winner, got {winners}"
    assert len(lock_errors) == 7
    assert json.loads(path.read_text())["session_id"] == winners[0]


def test_sigterm_while_holding_the_lock_releases_it(tmp_path):
    lock_path = tmp_path / ".workflow.lock"
    code = (
        "import sys, time, pathlib; sys.path.insert(0, %r)\n"
        "from harness_core.lock import workflow_lock\n"
        "with workflow_lock('term-test', path=pathlib.Path(%r)):\n"
        "    print('held', flush=True)\n"
        "    time.sleep(30)\n"
    ) % (ROOT, str(lock_path))
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    assert lock_path.exists()
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=10)
    assert proc.returncode in (128 + signal.SIGTERM, -signal.SIGTERM)
    assert not lock_path.exists()
