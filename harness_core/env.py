"""Minimal secret lookup for optional hosted providers: the process environment first, then
a `.env` file (KEY=VALUE lines, `#` comments, optional `export ` prefix, optional quotes).
No python-dotenv dependency. The VALUE is returned to the caller and nowhere else -- this
module never logs, prints, or stores it, and callers must not either (see
harness_core.providers.HostedFreeProvider's __repr__)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DEFAULT_DOTENV_PATH = Path(".env")


def _parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def read_env_var(name: str, dotenv_path: Optional[Path] = None) -> Optional[str]:
    """Returns the variable's value from os.environ, else from the `.env` file, else None.
    An empty string counts as unset."""
    value = os.environ.get(name)
    if value:
        return value
    path = dotenv_path if dotenv_path is not None else DEFAULT_DOTENV_PATH
    if not path.exists():
        return None
    return _parse_dotenv(path.read_text()).get(name) or None
