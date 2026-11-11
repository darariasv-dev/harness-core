"""Generic stage-record shapes shared across a pipeline harness. Deliberately small: most of
a real pipeline's records (what's being screened, what's being assessed) are inherently
domain-specific and belong in the consuming project, not here. Only the two shapes that carry
no domain concept at all live in this module."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class GateResult:
    """A single pass/fail deterministic check, with the evidence behind the verdict --
    never a bare boolean. `name` should be human-readable enough to show in a report as-is."""
    name: str
    passed: bool
    evidence: str


@dataclass
class UsageRecord:
    """The four measured-usage fields a headless model call's own envelope reports --
    never a chars/4 estimate dressed up as a real count (see harness_core.ledger for the
    estimated/measured distinction)."""
    input: Optional[int] = None
    cache_creation: Optional[int] = None
    cache_read: Optional[int] = None
    output: Optional[int] = None


@dataclass
class OpenStatusEvidence:
    """Live, uncached evidence for whether a URL-backed resource is still open/available --
    see harness_core.evidence.check_open_status. Generic across "is this still open" checks
    of any kind, not specific to any one resource type."""
    checked_at: Optional[str] = None
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    redirect_chain: list = field(default_factory=list)
    status: Optional[str] = None  # "open" | "closed" | "unknown"
