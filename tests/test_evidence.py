from unittest.mock import MagicMock, patch

from harness_core.evidence import check_open_status, STATUS_CLOSED, STATUS_OPEN, STATUS_UNKNOWN


def _fake_response(status_code=200, url="https://example.com/a", history=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.url = url
    resp.history = history or []
    return resp


def _hop(url):
    h = MagicMock()
    h.url = url
    return h


def test_open_on_clean_200():
    with patch("httpx.get", return_value=_fake_response(status_code=200)):
        evidence = check_open_status("https://example.com/a")
    assert evidence.status == STATUS_OPEN
    assert evidence.http_status == 200


def test_closed_on_non_200():
    with patch("httpx.get", return_value=_fake_response(status_code=404)):
        evidence = check_open_status("https://example.com/a")
    assert evidence.status == STATUS_CLOSED


def test_closed_on_error_redirect_marker_even_with_200_final():
    final = _fake_response(status_code=200, url="https://example.com/index?error=true", history=[_hop("https://example.com/a/1")])
    with patch("httpx.get", return_value=final):
        evidence = check_open_status("https://example.com/a/1", error_redirect_markers=("error=true",))
    assert evidence.status == STATUS_CLOSED
    assert evidence.http_status == 200


def test_unknown_on_network_failure():
    import httpx
    with patch("httpx.get", side_effect=httpx.RequestError("boom")):
        evidence = check_open_status("https://example.com/a")
    assert evidence.status == STATUS_UNKNOWN


def test_unknown_for_empty_url():
    evidence = check_open_status("")
    assert evidence.status == STATUS_UNKNOWN
