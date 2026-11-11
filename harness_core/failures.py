"""Typed failure classes and a budget that decrements only on success. Domain-agnostic by
construction: nothing here knows what kind of thing a "call" is for, only whether it
succeeded, timed out, hit a rate limit, returned something unparseable, or was otherwise
unavailable."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureClass(str, Enum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    INVALID_RESPONSE = "invalid_response"
    UNAVAILABLE = "unavailable"


def classify_headless_failure(exc: Exception) -> FailureClass:
    """Classifies a headless-call-style exception into one of the four failure classes.
    Order matters: quota/rate-limit checked first (via an optional `likely_quota_exhausted`
    attribute the caller's exception type may set), then a literal 'timeout' in the message,
    then a JSON/schema-shaped failure as invalid_response, else unavailable."""
    if getattr(exc, "likely_quota_exhausted", False):
        return FailureClass.RATE_LIMITED
    text = str(exc).lower()
    if "timeout" in text or "timed out" in text:
        return FailureClass.TIMEOUT
    if "json" in text or "schema" in text or "missing required key" in text:
        return FailureClass.INVALID_RESPONSE
    return FailureClass.UNAVAILABLE


@dataclass
class Budget:
    """Decrements ONLY on a token-bearing success -- a timeout, rate-limit, invalid response,
    or unavailable source never consumes budget. `used` never exceeds `total`;
    `record_success` past that point is a caller bug, not silently absorbed."""
    total: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return self.total - self.used

    def has_remaining(self) -> bool:
        return self.remaining > 0

    def record_success(self) -> None:
        if self.used >= self.total:
            raise RuntimeError(f"Budget already exhausted ({self.used}/{self.total}) -- caller must check has_remaining() first")
        self.used += 1

    def record_failure(self, failure_class: FailureClass) -> None:
        """Deliberately a no-op on `used` -- exists so callers have one place to log a
        failure's class without being tempted to also decrement budget for it."""
        return None
