"""Loader for small, versioned YAML policy files -- the "versioned + content-hashed"
convention this harness applies to every policy input that can change a cached result's
outcome (see harness_core.cache): `load_yaml_policy` returns the parsed data alongside a
sha256 of the raw file text, so a caller that needs to fold a policy's identity into a cache
key always can."""
from __future__ import annotations

import hashlib
from pathlib import Path


def load_yaml_policy(path: Path) -> tuple[dict, str]:
    """Returns ({}, "") if the file doesn't exist -- a missing policy file is never an
    error, just an empty policy; callers apply their own safe default."""
    import yaml

    if not path.exists():
        return {}, ""
    text = path.read_text()
    return (yaml.safe_load(text) or {}), hashlib.sha256(text.encode()).hexdigest()


def write_yaml_policy(path: Path, data: dict, preserve_header_comments: bool = True) -> None:
    """Writes `data` back to `path`. PyYAML's safe_dump has no comment-preservation mode, so
    when `preserve_header_comments` is True (the default) this re-prepends the ORIGINAL
    file's leading `#`-comment block (if any) -- the human-authored documentation at the top
    of a policy file survives a write, even though inline comments elsewhere can't."""
    import yaml

    header = ""
    if preserve_header_comments and path.exists():
        original_text = path.read_text()
        header_lines = []
        for line in original_text.splitlines():
            if line.strip().startswith("#") or not line.strip():
                header_lines.append(line)
            else:
                break
        header = ("\n".join(header_lines) + "\n\n") if header_lines else ""
    path.write_text(header + yaml.safe_dump(data, sort_keys=False))
