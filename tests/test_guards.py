import smtplib
import socket
import subprocess
import urllib.request

import httpx
import pytest

from harness_core.guards import OfflineViolation, network_guard


def test_blocks_subprocess_popen():
    with network_guard():
        with pytest.raises(OfflineViolation):
            subprocess.Popen(["echo", "hi"])


def test_blocks_raw_socket():
    with network_guard():
        with pytest.raises(OfflineViolation):
            socket.socket()


def test_blocks_urllib():
    with network_guard():
        with pytest.raises(OfflineViolation):
            urllib.request.urlopen("https://example.com")


def test_blocks_smtplib():
    with network_guard():
        with pytest.raises(OfflineViolation):
            smtplib.SMTP()


def test_blocks_httpx_get():
    with network_guard():
        with pytest.raises(OfflineViolation):
            httpx.get("https://example.com")


def test_blocks_httpx_post():
    with network_guard():
        with pytest.raises(OfflineViolation):
            httpx.post("https://example.com")


def test_guard_releases_after_context_exits():
    with network_guard():
        pass
    # After the context, socket.socket should be the real constructor again (no exception
    # from merely instantiating -- we don't actually connect anywhere).
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.close()


def test_caller_can_add_its_own_patch_on_the_yielded_stack():
    from unittest.mock import patch

    class Thing:
        @staticmethod
        def do_it():
            return "real"

    with network_guard() as stack:
        stack.enter_context(patch.object(Thing, "do_it", side_effect=RuntimeError("blocked")))
        with pytest.raises(RuntimeError):
            Thing.do_it()
