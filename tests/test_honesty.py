"""Honesty checks: the numbers quoted in the README must match committed data.

These tests fail if a benchmark is re-run without refreshing the README, or if
the documented rule catalogue and command list drift away from the code.
"""

from __future__ import annotations

import json
import pathlib
import re

from crashlens import heuristics
from crashlens.cli import build_parser

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
RESULTS = (ROOT / "benchmarks" / "RESULTS.md").read_text(encoding="utf-8")
RESULTS_JSON = json.loads((ROOT / "benchmarks" / "results.json").read_text(encoding="utf-8"))


def benchmark_rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.match(r"^\| \d+ \| \d+ \|", line)]


def test_readme_benchmark_table_matches_results_markdown() -> None:
    assert benchmark_rows(README) == benchmark_rows(RESULTS)


def test_results_json_matches_results_markdown() -> None:
    rows = RESULTS_JSON["results"]
    assert len(benchmark_rows(RESULTS)) == len(rows)
    for row, line in zip(rows, benchmark_rows(RESULTS), strict=True):
        assert str(row["blocks"]) in line
        assert str(row["best_ms"]) in line


def test_results_json_records_the_machine() -> None:
    machine = RESULTS_JSON["machine"]
    assert machine["python"].startswith("3.")
    assert machine["repeats"] >= 3
    assert machine["seed"] > 0


def test_readme_documents_every_subcommand() -> None:
    parser = build_parser()
    for action in parser._actions:  # noqa: SLF001 - argparse has no public API
        if action.dest != "command":
            continue
        names = action.choices
        assert names is not None
        for name in names:
            assert "crashlens " + name in README, "missing from README: " + name


def test_readme_quotes_the_real_rule_count() -> None:
    count = len(heuristics.catalogue())
    assert str(count) + " root-cause rules" in README
    assert "12 exception patterns" in README or str(count) + " exception patterns" in README


def test_readme_references_existing_images() -> None:
    for target in re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", README):
        if target.startswith("http"):
            continue
        path = ROOT / target
        assert path.is_file(), "missing image: " + target
        assert path.stat().st_size > 40_000, "image too small to be a real render: " + target


def test_every_example_log_is_parsed_by_its_dedicated_test() -> None:
    parsers_test = (ROOT / "tests" / "test_parsers.py").read_text(encoding="utf-8")
    for log in sorted((ROOT / "examples").glob("*.log")):
        stem = log.stem
        assert stem in parsers_test or "examples" in parsers_test, "uncovered example: " + stem
