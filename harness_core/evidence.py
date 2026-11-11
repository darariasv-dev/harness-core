"""A live, uncached open/closed check for any URL-backed resource: "Open-status evidence =
live uncached request with http_status/final_url/redirect_chain/fetched_at; non-200 final or
an error-marker redirect = closed." Deliberately narrow -- purely status code and redirect
chain, never page-body text matching (a different, project-specific concern that belongs
outside this package). Never raises -- a network failure is "unknown," never asserted open OR
closed either way."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from harness_core.records import OpenStatusEvidence

STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_UNKNOWN = "unknown"


def check_open_status(url: str, error_redirect_markers: tuple = (), timeout: int = 15) -> OpenStatusEvidence:
    """`error_redirect_markers`: substrings that, if present in the final URL or ANY hop of
    the redirect chain, mark the resource closed even though the final response itself may
    be a normal HTTP 200 (e.g. a redirect to a generic error/index page carrying
    "?error=true" -- confirmed as a real pattern this check exists specifically to catch)."""
    import httpx

    if not url:
        return OpenStatusEvidence(checked_at=datetime.now(timezone.utc).isoformat(), status=STATUS_UNKNOWN)
    try:
        resp = httpx.get(
            url, follow_redirects=True, timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; harness-core/0.1)"},
        )
    except httpx.RequestError:
        return OpenStatusEvidence(checked_at=datetime.now(timezone.utc).isoformat(), status=STATUS_UNKNOWN)

    redirect_chain = [str(r.url) for r in resp.history] + [str(resp.url)]
    error_redirect = any(
        marker in hop for hop in redirect_chain for marker in error_redirect_markers
    )
    status = STATUS_CLOSED if (resp.status_code != 200 or error_redirect) else STATUS_OPEN
    return OpenStatusEvidence(
        checked_at=datetime.now(timezone.utc).isoformat(),
        http_status=resp.status_code,
        final_url=str(resp.url),
        redirect_chain=redirect_chain,
        status=status,
    )
