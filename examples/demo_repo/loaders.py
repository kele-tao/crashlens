"""Small persistence helpers used by the batch importer."""

from __future__ import annotations

import pathlib


def read_batch(root: str, name: str) -> list[str]:
    """Read one batch file and return its non empty lines."""
    path = pathlib.Path(root) / name
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
