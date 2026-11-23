"""Materialise the deterministic git history used by the annotate examples.

The demo repository is committed as plain source files; this script turns it
into a real two-commit git repository so git blame and blame-since can be
demonstrated offline and reproduced byte for byte on any machine:

    python examples/init_demo_repo.py

Commit one (2025-01-06, Alice Chen) adds the pipeline in its safe form.
Commit two (2025-02-11, Priya Nair) removes the guard around the "items" key,
which is the regression the bundled crash logs were captured against.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
DEMO = HERE / "demo_repo"
PIPELINE = DEMO / "pipeline.py"

SAFE = '''"""Order enrichment pipeline.

This module is intentionally small: it exists so the crashlens examples have a
real repository to blame.  enrich() is the entry point the HTTP layer calls.
"""

from __future__ import annotations

import json
from typing import Any


def decode(raw: str) -> dict[str, Any]:
    """Parse the JSON body a partner sent us."""
    return json.loads(raw)


def pick_sku(document: dict[str, Any]) -> str:
    """Return the sku of the first line item."""
    items = document.get("items") or []
    if not items:
        return ""
    return items[0]["sku"]


def enrich(raw: str) -> dict[str, Any]:
    """Decode and normalise one checkout payload."""
    try:
        document = decode(raw)
        return {"sku": pick_sku(document), "source": "checkout"}
    except ValueError as exc:
        raise RuntimeError("order enrichment failed for checkout") from exc
'''

REGRESSION = SAFE.replace(
    '    items = document.get("items") or []',
    '    items = document["items"]',
)

COMMITS = [
    (
        "Alice Chen",
        "alice@acme.test",
        "2025-01-06T10:12:00+00:00",
        "feat: order enrichment pipeline with JSON decoding",
        SAFE,
    ),
    (
        "Priya Nair",
        "priya@acme.test",
        "2025-02-11T09:30:00+00:00",
        "refactor: trust partner payload in pick_sku",
        REGRESSION,
    ),
]


def remove_history(path: pathlib.Path) -> None:
    """Delete a .git directory, clearing read-only bits Windows may leave behind."""
    import stat

    def on_error(func, target, _exc_info):  # type: ignore[no-untyped-def]
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    shutil.rmtree(path, onerror=on_error)


def run(args: list[str], env: dict[str, str]) -> None:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(DEMO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if proc.returncode != 0:
        raise SystemExit("git " + " ".join(args) + " failed:\n" + (proc.stderr or proc.stdout))


def main(argv: list[str]) -> int:
    if not DEMO.is_dir():
        raise SystemExit("missing demo repository: " + str(DEMO))
    if (DEMO / ".git").exists() and "--force" not in argv:
        print("demo repository already initialised at", DEMO)
        return 0
    if (DEMO / ".git").exists():
        remove_history(DEMO / ".git")
    env = dict(os.environ)
    env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
    run(["init", "-b", "main", "-q"], env)
    run(["config", "user.name", COMMITS[0][0]], env)
    run(["config", "user.email", COMMITS[0][1]], env)
    for name, email, when, summary, source in COMMITS:
        # newline="\n" keeps the blob identical on Windows and Linux, so the
        # commit hashes quoted in the README and docs are reproducible.
        PIPELINE.write_text(source, encoding="utf-8", newline="\n")
        env.update(
            {
                "GIT_AUTHOR_NAME": name,
                "GIT_AUTHOR_EMAIL": email,
                "GIT_AUTHOR_DATE": when,
                "GIT_COMMITTER_NAME": name,
                "GIT_COMMITTER_EMAIL": email,
                "GIT_COMMITTER_DATE": when,
            }
        )
        run(["add", "-A"], env)
        run(["commit", "-q", "-m", summary], env)
    log = subprocess.run(
        ["git", "log", "--format=%h %ad %an %s", "--date=short"],
        cwd=str(DEMO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    sys.stdout.write(log.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
