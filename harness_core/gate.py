"""Helpers over a list of harness_core.records.GateResult -- a hard, binary pass/fail check
with the evidence behind it, never a bare boolean. This module has no opinion about what any
particular gate checks; a consuming project defines its own gates and hands the results here
only to combine/summarize them."""
from __future__ import annotations

from harness_core.records import GateResult


def all_passed(gates: list[GateResult]) -> bool:
    return all(g.passed for g in gates)


def failed_gates(gates: list[GateResult]) -> list[GateResult]:
    return [g for g in gates if not g.passed]


def summarize(gates: list[GateResult]) -> str:
    """One line per gate, `name: PASS/FAIL -- evidence`."""
    return "\n".join(f"{g.name}: {'PASS' if g.passed else 'FAIL'} -- {g.evidence}" for g in gates)
