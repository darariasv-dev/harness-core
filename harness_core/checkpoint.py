"""A fixed-schema checkpoint block: COMMAND/COMPLETED/PHASE/PILOT/USAGE/BLOCKER/NEXT/UPDATED,
always in that order, always all eight fields present (an empty field still gets its label,
e.g. "PILOT: n/a"). Meant to be the one machine-parseable block at the top of a project's own
running checkpoint document -- everything else in that document can stay free-form prose."""
from __future__ import annotations

import re
import textwrap
from typing import Optional

FIELDS = ("COMMAND", "COMPLETED", "PHASE", "PILOT", "USAGE", "BLOCKER", "NEXT", "UPDATED")

_LABEL_WIDTH = 12  # "COMMAND:    " -- longest label ("COMPLETED") is 9 chars + ":" + padding


def format_checkpoint_block(fields: dict) -> str:
    """`fields` must have exactly the keys in FIELDS (a missing key raises, so a caller can
    never silently omit one). Wraps long values to align continuation lines under the first
    word after the label, matching a hand-written checkpoint's own visual convention."""
    missing = [f for f in FIELDS if f not in fields]
    if missing:
        raise ValueError(f"missing required checkpoint field(s): {missing}")

    lines = []
    for name in FIELDS:
        label = f"{name}:".ljust(_LABEL_WIDTH)
        value = str(fields[name] or "n/a")
        wrapped = textwrap.wrap(value, width=88 - _LABEL_WIDTH) or [""]
        lines.append(label + wrapped[0])
        for cont in wrapped[1:]:
            lines.append(" " * _LABEL_WIDTH + cont)
    return "\n".join(lines)


def parse_checkpoint_block(text: str) -> Optional[dict]:
    """Returns None if `text` doesn't contain a recognizable checkpoint block (no line
    starting with "COMMAND:"). Reconstructs each field's full (unwrapped) value by joining
    its own line plus any indented continuation lines that follow it, up to the next
    labeled line."""
    lines = text.splitlines()
    label_re = re.compile(r"^([A-Z]+):\s*(.*)$")
    start = next((i for i, l in enumerate(lines) if label_re.match(l) and label_re.match(l).group(1) == "COMMAND"), None)
    if start is None:
        return None

    result: dict = {}
    current_field = None
    current_parts: list[str] = []
    for line in lines[start:]:
        match = label_re.match(line)
        if match and match.group(1) in FIELDS:
            if current_field:
                result[current_field] = " ".join(current_parts).strip()
            current_field = match.group(1)
            current_parts = [match.group(2)]
        elif current_field and (line.startswith(" ") or not line.strip()):
            if line.strip():
                current_parts.append(line.strip())
        else:
            break
    if current_field:
        result[current_field] = " ".join(current_parts).strip()
    return result
