"""Report rendering tests: terminal, JSON and HTML output."""

from __future__ import annotations

import json
import pathlib

from crashlens.cluster import cluster_crashes, rank
from crashlens.engine import analyse
from crashlens.parsers import parse_paths
from crashlens.repo import Repo
from crashlens.report import (
    cluster_payload,
    dump_json,
    render_html,
    render_terminal,
    report_payload,
    short_time,
)
from crashlens.style import Painter

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
DEMO = EXAMPLES / "demo_repo"


def analysis():
    return analyse([str(EXAMPLES)], repo_path=str(DEMO))


def test_short_time_formats_and_handles_none() -> None:
    assert short_time(None) == "-"
    assert len(short_time(analysis().crashes[0].timestamp)) == 16


def test_terminal_report_has_header_and_bars() -> None:
    data = analysis()
    text = render_terminal(data.clusters, data.crashes, data.repo, Painter(False))
    assert "crashes in" in text
    assert "#" in text
    assert "actionable" in text


def test_terminal_report_without_colour_has_no_escapes() -> None:
    data = analysis()
    text = render_terminal(data.clusters, data.crashes, data.repo, Painter(False))
    assert chr(27) not in text


def test_terminal_report_with_colour_has_escapes() -> None:
    data = analysis()
    text = render_terminal(data.clusters, data.crashes, data.repo, Painter(True))
    assert chr(27) in text


def test_terminal_report_limit_and_no_hints() -> None:
    data = analysis()
    text = render_terminal(
        data.clusters, data.crashes, data.repo, Painter(False), limit=1, show_hints=False
    )
    assert "root cause" not in text


def test_terminal_report_empty_input_is_helpful() -> None:
    text = render_terminal([], [], None, Painter(False))
    assert "no crashes found" in text
    assert "hint" in text


def test_json_payload_is_json_serialisable() -> None:
    data = analysis()
    payload = report_payload(data.clusters, data.crashes, data.repo)
    text = dump_json(payload)
    assert json.loads(text)["tool"] == "crashlens"
    assert text.endswith("\n")


def test_json_dump_sorts_keys() -> None:
    text = dump_json({"b": 1, "a": 2})
    assert text.index('"a"') < text.index('"b"')


def test_cluster_payload_includes_identity_fields() -> None:
    data = analysis()
    payload = cluster_payload(data.clusters[0], data.repo)
    for key in (
        "fingerprint",
        "label",
        "count",
        "languages",
        "first_seen",
        "last_seen",
        "diagnoses",
        "sample_traceback",
    ):
        assert key in payload
    assert len(payload["fingerprint"]) == 12


def test_cluster_payload_actionable_is_owned() -> None:
    data = analysis()
    python_cluster = next(cluster for cluster in data.clusters if cluster.languages == ["python"])
    payload = cluster_payload(python_cluster, data.repo)
    assert payload["actionable"]["owned"] is True


def test_html_report_contains_summary_and_svg() -> None:
    data = analysis()
    html = render_html(data.clusters, data.crashes, data.repo, generated_at="2025-01-01T00:00:00")
    assert html.startswith("<!doctype html>")
    assert "<svg" in html
    assert "<rect" in html
    assert "2025-01-01T00:00:00" in html
    assert "</html>" in html


def test_html_report_escapes_hostile_input() -> None:
    crash = parse_paths([str(EXAMPLES / "node_async_error.log")])[0]
    crash.segments[0] = crash.segments[0].__class__(
        exception_type="Error",
        message="<script>alert(1)</script>",
        frames=crash.segments[0].frames,
    )
    clusters = rank(cluster_crashes([crash]))
    html = render_html(clusters, [crash], None)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_report_without_repo_is_fine() -> None:
    crashes = parse_paths([str(EXAMPLES / "go_panic.log")])
    html = render_html(cluster_crashes(crashes), crashes, None)
    assert "not provided" in html


def test_cluster_payload_with_no_actionable_frame() -> None:
    crashes = parse_paths([str(EXAMPLES / "go_panic.log")])
    cluster = cluster_crashes(crashes)[0]
    payload = cluster_payload(cluster, Repo(DEMO))
    assert "actionable" in payload


def test_terminal_report_is_byte_identical_across_runs() -> None:
    first = analysis()
    second = analysis()
    a = render_terminal(first.clusters, first.crashes, first.repo, Painter(False))
    b = render_terminal(second.clusters, second.crashes, second.repo, Painter(False))
    assert a == b
