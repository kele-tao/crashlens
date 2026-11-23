"""CLI contract tests: exit codes, flags, JSON shape and HTML report."""

from __future__ import annotations

import json
import pathlib

import pytest

from crashlens.cli import main

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
DEMO = EXAMPLES / "demo_repo"
PY_LOG = str(EXAMPLES / "python_error.log")


def run(argv: list[str], capsys) -> tuple[int, str, str]:
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_help_exits_zero(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "crashlens" in capsys.readouterr().out


def test_version_prints_semver(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "1.0.0" in capsys.readouterr().out


def test_no_command_is_usage_error(capsys) -> None:
    code, out, _ = run([], capsys)
    assert code == 2
    assert "usage" in out.lower()


def test_unknown_flag_is_usage_error(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["cluster", "--nope"])
    assert excinfo.value.code == 2


def test_parse_prints_crash_count(capsys) -> None:
    code, out, _ = run(["parse", PY_LOG, "--no-color"], capsys)
    assert code == 0
    assert "2 crashes parsed" in out
    assert "KeyError" in out


def test_parse_json_has_frames_and_chain(capsys) -> None:
    code, out, _ = run(["parse", PY_LOG, "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    crash = payload["crashes"][0]
    assert crash["language"] == "python"
    assert len(crash["chain"]) == 2
    assert crash["chain"][1]["relation"] == "cause"
    assert crash["chain"][1]["frames"]


def test_parse_limit_truncates(capsys) -> None:
    code, out, _ = run(["parse", PY_LOG, "--json", "--limit", "1"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert len(payload["crashes"]) == 1
    assert payload["total"] == 2


def test_parse_plain_log_exits_one(capsys, tmp_path: pathlib.Path) -> None:
    log = tmp_path / "quiet.log"
    log.write_text("INFO all good\n", encoding="utf-8")
    code, _, err = run(["parse", str(log)], capsys)
    assert code == 1
    assert "no crash records" in err


def test_missing_input_is_usage_error(capsys) -> None:
    code, _, err = run(["parse", "no-such.log"], capsys)
    assert code == 2
    assert "not found" in err


def test_cluster_report_ranks_by_count(capsys) -> None:
    code, out, _ = run(["cluster", str(EXAMPLES), "--repo", str(DEMO), "--no-color"], capsys)
    assert code == 0
    assert "clusters" in out
    assert "actionable" in out


def test_cluster_json_is_deterministic(capsys) -> None:
    _, first, _ = run(["cluster", str(EXAMPLES), "--json"], capsys)
    _, second, _ = run(["cluster", str(EXAMPLES), "--json"], capsys)
    assert first == second
    payload = json.loads(first)
    assert payload["summary"]["crashes"] >= 9
    assert payload["clusters"]


def test_cluster_top_limits_rows(capsys) -> None:
    code, out, _ = run(["cluster", str(EXAMPLES), "--json", "--top", "2"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert len(payload["clusters"]) == 2
    assert payload["omitted_clusters"] >= 1


def test_cluster_html_is_self_contained(capsys, tmp_path: pathlib.Path) -> None:
    target = tmp_path / "report.html"
    code, _, err = run(["cluster", str(EXAMPLES), "--html", str(target), "--json"], capsys)
    assert code == 0
    assert target.exists()
    html = target.read_text(encoding="utf-8")
    assert "<svg" in html
    assert "http://" not in html.replace("http://www.w3.org", "")
    assert "crashlens" in html
    assert "wrote" in err


def test_cluster_min_count_filters_rare_clusters(capsys) -> None:
    code, out, _ = run(["cluster", str(EXAMPLES), "--json", "--min-count", "2"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["clusters"]
    assert all(cluster["count"] >= 2 for cluster in payload["clusters"])


def test_annotate_shows_source_and_blame(capsys) -> None:
    code, out, _ = run(["annotate", PY_LOG, "--repo", str(DEMO), "--no-color"], capsys)
    assert code == 0
    assert "pipeline.py" in out
    assert "blame" in out
    assert "Priya Nair" in out
    assert "days after that commit" in out


def test_annotate_no_blame_hides_attribution(capsys) -> None:
    code, out, _ = run(
        ["annotate", PY_LOG, "--repo", str(DEMO), "--no-blame", "--no-color"], capsys
    )
    assert code == 0
    assert "blame" not in out


def test_annotate_deepest_frame_flag(capsys) -> None:
    code, out, _ = run(
        ["annotate", PY_LOG, "--repo", str(DEMO), "--frame", "deepest", "--no-color"], capsys
    )
    assert code == 0
    assert "where" in out


def test_annotate_json_shape(capsys) -> None:
    code, out, _ = run(["annotate", PY_LOG, "--repo", str(DEMO), "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["location"].startswith("pipeline.py:")
    assert payload["blame"]["author"] == "Priya Nair"
    assert any(line["target"] for line in payload["source"])


def test_annotate_context_is_clamped(capsys) -> None:
    code, out, _ = run(
        ["annotate", PY_LOG, "--repo", str(DEMO), "--context", "100", "--json"], capsys
    )
    assert code == 0
    payload = json.loads(out)
    assert len(payload["source"]) <= 13


def test_annotate_without_crash_exits_two(capsys, tmp_path: pathlib.Path) -> None:
    log = tmp_path / "quiet.log"
    log.write_text("INFO all good\n", encoding="utf-8")
    code, _, err = run(["annotate", str(log), "--repo", str(DEMO)], capsys)
    assert code == 2
    assert "no crash records" in err


def test_rules_lists_catalogue(capsys) -> None:
    code, out, _ = run(["rules", "--no-color"], capsys)
    assert code == 0
    assert "root-cause rules" in out
    assert "none-optional" in out


def test_rules_json(capsys) -> None:
    code, out, _ = run(["rules", "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["total"] == len(payload["rules"])


def test_blame_since_reports_the_deploy(capsys) -> None:
    code, out, _ = run(
        ["blame-since", "HEAD~1", str(EXAMPLES), "--repo", str(DEMO), "--no-color"], capsys
    )
    assert code == 0
    assert "deploy window" in out
    assert "pipeline.py" in out
    assert "Priya Nair" in out


def test_blame_since_unrelated_window_exits_one(capsys) -> None:
    code, out, _ = run(
        ["blame-since", "HEAD", str(EXAMPLES / "go_panic.log"), "--repo", str(DEMO), "--no-color"],
        capsys,
    )
    assert code == 1
    assert "no crash frames touch" in out


def test_blame_since_json(capsys) -> None:
    code, out, _ = run(["blame-since", "HEAD~1", str(EXAMPLES), "--repo", str(DEMO), "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["changed_files"][0]["path"] == "pipeline.py"
    assert payload["matched_clusters"]


def test_blame_since_bad_revision_exits_two(capsys) -> None:
    code, _, err = run(["blame-since", "nope", PY_LOG, "--repo", str(DEMO)], capsys)
    assert code == 2
    assert "unknown revision" in err


def test_stdin_like_path_errors_cleanly(capsys) -> None:
    code, _, err = run(["cluster", "-"], capsys)
    assert code == 2
    assert "not found" in err


def test_encoding_flag_reads_latin1(capsys, tmp_path: pathlib.Path) -> None:
    log = tmp_path / "latin.log"
    log.write_bytes(
        "2025-01-01 10:00:00 ERROR caf\xe9\n"
        "Traceback (most recent call last):\n"
        '  File "/app/x.py", line 1, in f\n'
        "    pass\n"
        "ValueError: caf\xe9\n".encode("latin-1")
    )
    code, out, _ = run(["parse", str(log), "--encoding", "latin-1", "--json"], capsys)
    assert code == 0
    assert "caf" in out
