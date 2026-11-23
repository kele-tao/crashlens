"""Shared pytest fixtures.

The example repository ships as plain files; the git history used by the
blame tests is materialised once per session so a fresh clone can run the
whole suite offline.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "demo_repo"


@pytest.fixture(scope="session", autouse=True)
def demo_history() -> None:
    """Create the deterministic two-commit history for examples/demo_repo."""
    if (DEMO / ".git").exists():
        return
    subprocess.run(
        [sys.executable, str(ROOT / "examples" / "init_demo_repo.py")],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
    )
