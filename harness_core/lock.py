"""A single-writer workflow lock for a pipeline that runs as separate processes: a plain JSON
file (checkable before any database is opened), holding session_id, pid, and acquired_at.

Staleness is decided two ways, either of which frees the lock: the holder pid is no longer
alive (probed with signal 0), or the lock is older than STALE_AFTER_SECONDS. The pid check is
what makes a crashed or SIGTERM-killed holder stale immediately instead of after the time
limit; the time check remains for a pid that cannot be probed. `workflow_lock` also converts
SIGTERM into SystemExit while the lock is held so the `finally` that releases it actually
runs (a default TERM handler ends the process without running it; SIGKILL cannot be caught
by anyone, which is what the pid check covers)."""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LOCK_PATH = Path(".workflow.lock")
STALE_AFTER_SECONDS = 30 * 60


def _pid_alive(pid: int) -> bool:
    """True if a process with this pid exists. A PermissionError means it exists but belongs
    to another user -- treated as alive."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class LockHeldByAnotherSession(Exception):
    def __init__(self, holder: dict):
        self.holder = holder
        super().__init__(f"lock held by session {holder.get('session_id')!r} (pid {holder.get('pid')}), not stale")


@dataclass
class WorkflowLock:
    path: Path = LOCK_PATH

    def _read(self) -> Optional[dict]:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _is_stale(self, holder: dict) -> bool:
        acquired_at = holder.get("acquired_at")
        if not isinstance(acquired_at, (int, float)):
            return True
        pid = holder.get("pid")
        if isinstance(pid, int) and pid > 0 and not _pid_alive(pid):
            return True
        return (time.time() - acquired_at) > STALE_AFTER_SECONDS

    def clear_if_stale(self) -> Optional[dict]:
        """Removes a stale lock and returns the holder it removed; None if no lock or a live
        one. Never removes a live holder's lock."""
        existing = self._read()
        if existing is None:
            return None
        if self._is_stale(existing):
            self.path.unlink(missing_ok=True)
            return existing
        return None

    def acquire(self, session_id: str, paths: Optional[list] = None) -> None:
        """Raises LockHeldByAnotherSession if a non-stale lock from a DIFFERENT session_id
        exists. A stale lock, or one from the same session_id, is taken over silently.

        Acquiring an UNHELD lock is atomic and torn-read-free: the full payload is written to
        a uniquely-named temp file first, then published via `os.link` (fails with
        FileExistsError if the target already exists, and never exposes a partially-written
        file -- the target's directory entry only starts existing once the content behind it
        is already complete). Two processes racing to acquire an unheld lock can never both
        believe they succeeded, and a third process reading mid-race never sees an empty or
        truncated lock file. A plain read-then-write (the original implementation) had both
        problems: two processes could read "no lock" before either wrote one, and a reader
        could observe a lock file created but not yet fully written."""
        payload = json.dumps({
            "session_id": session_id, "pid": os.getpid(), "paths": paths or [], "acquired_at": time.time(),
        }).encode()
        tmp_path = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
        tmp_path.write_bytes(payload)
        try:
            os.link(tmp_path, self.path)
        except FileExistsError:
            pass
        else:
            tmp_path.unlink(missing_ok=True)
            return
        try:
            existing = self._read()
            if existing is not None and existing.get("session_id") != session_id and not self._is_stale(existing):
                raise LockHeldByAnotherSession(existing)
            # Stale, or our own session reacquiring -- os.replace is an atomic overwrite, so
            # a concurrent reader never sees a torn file here either.
            os.replace(tmp_path, self.path)
        finally:
            tmp_path.unlink(missing_ok=True)

    def release(self, session_id: str) -> None:
        """No-op if the lock is missing or held by a different session."""
        existing = self._read()
        if existing is not None and existing.get("session_id") == session_id:
            self.path.unlink(missing_ok=True)

    def is_held(self) -> bool:
        existing = self._read()
        return existing is not None and not self._is_stale(existing)


@contextmanager
def workflow_lock(session_id: Optional[str] = None, paths: Optional[list] = None, path: Path = LOCK_PATH):
    """Run every pipeline command inside this. Acquires on enter, releases on exit -- including
    when the body raises or the process receives SIGTERM."""
    import signal

    sid = session_id or f"pipeline-{os.getpid()}"
    lock = WorkflowLock(path=path)
    lock.acquire(sid, paths=paths)
    previous = None
    installed = False
    try:
        previous = signal.getsignal(signal.SIGTERM)

        def _on_term(signum, frame):
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, _on_term)
        installed = True
    except (ValueError, OSError):
        installed = False  # not the main thread, or no signal support -- the pid check covers it
    try:
        yield lock
    finally:
        lock.release(sid)
        if installed:
            try:
                signal.signal(signal.SIGTERM, previous if previous is not None else signal.SIG_DFL)
            except (ValueError, OSError):
                pass
