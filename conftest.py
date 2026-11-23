"""Make 'pytest' work from a fresh clone without installing the package.

The console script and `pip install -e .` remain the supported install paths;
this shim only keeps `pytest -q` working when someone clones the repository and
runs the suite immediately, which is what most reviewers do first.
"""

from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
