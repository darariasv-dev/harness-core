"""Active, enforced offline-isolation guard. An application-level monkeypatch of specific
Python callables (stdlib network/process primitives, plus httpx) -- NOT an operating-system
sandbox, a container, or any kernel-enforced boundary, and it does not defend against
arbitrary code execution. A sufficiently low-level bypass (a compiled extension calling
execve directly, ctypes into libc, or any path that reaches a primitive this guard doesn't
know about) would not be caught. What it DOES reliably catch: every network/process path the
stdlib (`socket`, `urllib.request`, `smtplib`) and `httpx` actually use, plus process launches
generally -- `subprocess.Popen` is the single low-level primitive `subprocess.run`/`call`/
`check_output`/`check_call` and most browser-automation launchers all funnel through, so
patching it there is a structural backstop for "some other, not-yet-imagined code path
launches a process," not just a named function.

A consuming project should compose this with its OWN additional patches for its own
real-network/real-action entry points (a model-call client, a browser-automation module, a
credential store) -- this module only owns the generic stdlib/httpx/process layer."""
from __future__ import annotations

import contextlib
import smtplib
import socket
import subprocess
import urllib.request
from typing import Iterator
from unittest.mock import patch


class OfflineViolation(RuntimeError):
    """Raised the instant a real network call or process launch happens while the guard is
    active -- fail-closed, never a warning."""

    def __init__(self, what: str):
        super().__init__(f"blocked by offline guard: attempted {what}")


def _blocked(what: str):
    def _raise(*args, **kwargs):
        raise OfflineViolation(what)
    return _raise


@contextlib.contextmanager
def network_guard() -> Iterator[contextlib.ExitStack]:
    """Blocks, for the duration of the `with` block: raw sockets, urllib, smtplib; httpx's
    request-issuing entry points; and any process launch via subprocess.Popen. Yields the
    underlying ExitStack so a caller can `stack.enter_context(patch.object(...))` its own
    additional, project-specific patches on the SAME guard scope."""
    import httpx

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(subprocess, "Popen", side_effect=_blocked("subprocess.Popen (external process launch)")))
        stack.enter_context(patch.object(socket, "socket", side_effect=_blocked("a raw socket connection")))
        stack.enter_context(patch.object(urllib.request, "urlopen", side_effect=_blocked("urllib.request.urlopen")))
        stack.enter_context(patch.object(smtplib, "SMTP", side_effect=_blocked("smtplib.SMTP (real email send)")))
        stack.enter_context(patch.object(smtplib, "SMTP_SSL", side_effect=_blocked("smtplib.SMTP_SSL (real email send)")))
        stack.enter_context(patch.object(httpx, "get", side_effect=_blocked("httpx.get")))
        stack.enter_context(patch.object(httpx, "post", side_effect=_blocked("httpx.post")))
        stack.enter_context(patch.object(httpx.Client, "send", side_effect=_blocked("httpx.Client.send")))
        yield stack
