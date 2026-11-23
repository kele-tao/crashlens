"""Renderers: terminal summary, deterministic JSON and a self-contained HTML report."""

from __future__ import annotations

import html
import json
from datetime import datetime

from .cluster import Cluster, summary
from .fingerprint import fingerprint_parts, normalise_message, normalise_type
from .models import Crash
from .repo import Repo
from .style import Painter

BAR_WIDTH = 34
MAX_HTML_BARS = 12


def short_time(stamp: datetime | None) -> str:
    """Compact timestamp used in tables."""
    if stamp is None:
        return "-"
    return stamp.strftime("%Y-%m-%d %H:%M")


def _local_iso(stamp: datetime | None) -> str | None:
    return stamp.isoformat() if stamp is not None else None


def cluster_payload(cluster: Cluster, repo: Repo | None) -> dict[str, object]:
    """JSON-safe description of one cluster."""
    sample = cluster.sample
    assert sample is not None
    actionable, deepest = cluster.actionable(repo)
    payload: dict[str, object] = {
        "fingerprint": cluster.key,
        "label": cluster.label,
        "count": cluster.count,
        "languages": cluster.languages,
        "exception": normalise_type(sample.exception_type),
        "message": normalise_message(sample.message),
        "chain": cluster.signature_chain(),
        "first_seen": _local_iso(cluster.first_seen),
        "last_seen": _local_iso(cluster.last_seen),
        "sources": cluster.sources,
        "signature": list(fingerprint_parts(sample)),
        "diagnoses": [diagnosis.as_dict() for diagnosis in cluster.diagnoses()],
        "sample_traceback": sample.raw,
    }
    if actionable is not None:
        payload["actionable"] = {
            "file": actionable.file,
            "line": actionable.line,
            "function": actionable.function,
            "location": actionable.location,
            "owned": bool(repo is not None and repo.is_owned(actionable)),
        }
    else:
        payload["actionable"] = None
    payload["deepest"] = (
        {
            "file": deepest.file,
            "line": deepest.line,
            "function": deepest.function,
        }
        if deepest is not None
        else None
    )
    return payload


def report_payload(
    clusters: list[Cluster],
    crashes: list[Crash],
    repo: Repo | None,
    limit: int | None = None,
) -> dict[str, object]:
    """Full JSON document produced by `cluster --json`."""
    selected = clusters if limit is None else clusters[:limit]
    return {
        "tool": "crashlens",
        "version": "1.0.0",
        "generated_by": "crashlens cluster",
        "summary": summary(crashes),
        "repo": str(repo.root) if repo is not None else None,
        "clusters": [cluster_payload(cluster, repo) for cluster in selected],
        "omitted_clusters": max(0, len(clusters) - len(selected)),
    }


def render_terminal(
    clusters: list[Cluster],
    crashes: list[Crash],
    repo: Repo | None,
    painter: Painter,
    limit: int | None = None,
    show_hints: bool = True,
) -> str:
    """Terminal report: one ranked table followed by per-cluster details."""
    out: list[str] = []
    data = summary(crashes)
    languages = data["languages"]
    language_text = ", ".join(
        key + " " + str(value) for key, value in sorted(languages.items())  # type: ignore[union-attr]
    )
    out.append(
        painter.bold(str(data["crashes"]))
        + " crashes in "
        + painter.bold(str(len(clusters)))
        + " clusters"
        + (("  [" + language_text + "]") if language_text else "")
    )
    if data["first_seen"] and data["last_seen"]:
        out.append(
            painter.dim("window  ")
            + str(data["first_seen"]).replace("T", " ")[:19]
            + " .. "
            + str(data["last_seen"]).replace("T", " ")[:19]
        )
    out.append("")
    selected = clusters if limit is None else clusters[:limit]
    if not selected:
        out.append(painter.yellow("no crashes found"))
        out.append("hint: pass a log file or a directory containing *.log files")
        return "\n".join(out)
    peak = max(cluster.count for cluster in selected)
    out.append(
        painter.dim("  #  count  bar" + " " * (BAR_WIDTH - 2) + " fingerprint   cluster")
    )
    for rank, cluster in enumerate(selected, 1):
        filled = max(1, round(BAR_WIDTH * cluster.count / peak))
        bar = painter.paint("#" * filled, "\x1b[36m") + painter.dim("-" * (BAR_WIDTH - filled))
        out.append(
            "  "
            + str(rank).rjust(1)
            + "  "
            + painter.bold(str(cluster.count).rjust(5))
            + "  "
            + bar
            + "  "
            + painter.dim(cluster.key)
            + "  "
            + cluster.label
        )
    out.append("")
    for rank, cluster in enumerate(selected, 1):
        sample = cluster.sample
        assert sample is not None
        actionable, _ = cluster.actionable(repo)
        out.append(
            painter.cyan("#" + str(rank))
            + " "
            + painter.bold(cluster.label)
            + "  "
            + painter.dim(
                str(cluster.count)
                + "x  "
                + short_time(cluster.first_seen)
                + " -> "
                + short_time(cluster.last_seen)
                + "  "
                + ", ".join(cluster.languages)
            )
        )
        if sample.message:
            message = normalise_message(sample.message)
            out.append("   message   " + (message[:110] + ("..." if len(message) > 110 else "")))
        if len(sample.segments) > 1:
            out.append("   chain     " + " <- ".join(cluster.signature_chain()))
        if actionable is not None:
            out.append("   actionable " + actionable.location)
        if show_hints:
            for diagnosis in cluster.diagnoses()[:1]:
                out.append("   root cause " + diagnosis.title + "  [" + diagnosis.rule + "]")
                out.append("   next step  " + diagnosis.next_step)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_html(
    clusters: list[Cluster],
    crashes: list[Crash],
    repo: Repo | None,
    title: str = "crashlens report",
    generated_at: str | None = None,
) -> str:
    """Self-contained HTML report with inline SVG bars and no external assets."""
    data = summary(crashes)
    selected = clusters[:MAX_HTML_BARS]
    peak = max((cluster.count for cluster in selected), default=1)
    rows: list[str] = []
    for rank, cluster in enumerate(selected, 1):
        sample = cluster.sample
        assert sample is not None
        actionable, _ = cluster.actionable(repo)
        width = max(2, int(150 * cluster.count / peak))
        diagnosis = cluster.diagnoses()
        hint = diagnosis[0].rule if diagnosis else "-"
        rows.append(
            "<tr>"
            + "<td class=num>" + str(rank) + "</td>"
            + "<td class=barcell><svg width=180 height=18 role=img aria-label='count bar'>"
            + "<rect x=0 y=2 width=" + str(width) + " height=14 rx=3 fill='#22d3ee'/>"
            + "<text x=" + str(width + 6) + " y=14 class=bar>" + str(cluster.count) + "x</text>"
            + "</svg></td>"
            + "<td class=mono>" + html.escape(cluster.label) + "</td>"
            + "<td class=msg>" + html.escape(normalise_message(sample.message) or "-") + "</td>"
            + "<td>" + html.escape(", ".join(cluster.languages)) + "</td>"
            + "<td class=mono>" + html.escape(str(actionable.location) if actionable else "-") + "</td>"
            + "<td class=when>" + html.escape(short_time(cluster.first_seen)) + "</td>"
            + "<td class=when>" + html.escape(short_time(cluster.last_seen)) + "</td>"
            + "<td class=hintcell>" + html.escape(hint) + "</td>"
            + "</tr>"
        )
    lang_text = ", ".join(
        key + " " + str(value) for key, value in sorted(data["languages"].items())  # type: ignore[union-attr]
    )
    repo_text = str(repo.root) if repo is not None else "not provided"
    stamp = generated_at or datetime.now().isoformat(timespec="seconds")
    return "\n".join(
        [
            "<!doctype html>",
            "<html lang=en><head><meta charset=utf-8>",
            "<title>" + html.escape(title) + "</title>",
            "<style>",
            "body{margin:0;background:#0b0f17;color:#d1d5db;",
            "font:15px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}",
            "header{padding:28px 32px;border-bottom:1px solid #1f2937}",
            "h1{margin:0 0 6px;font-size:24px;color:#f8fafc}",
            ".sub{color:#8b9bb4}",
            "main{padding:24px 32px 40px;overflow-x:auto}",
            "table{border-collapse:collapse;width:100%;margin-top:18px}",
            "th,td{text-align:left;padding:8px 12px;border-bottom:1px solid #1b2432;vertical-align:middle}",
            "th:last-child,td:last-child{padding-right:28px}",
            "th{color:#93c5fd;font-weight:600;font-size:13px;text-transform:uppercase}",
            "td.num{color:#fbbf24;font-weight:700}",
            ".mono{color:#e5e7eb}",
            ".hint{color:#8b9bb4}",
            ".msg{color:#9ca3af;max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
            ".when{color:#8b9bb4;font-size:13px;white-space:nowrap}",
            ".barcell{white-space:nowrap}",
            ".hintcell{color:#8b9bb4;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
            ".msg{color:#9ca3af;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
            ".bar{fill:#8b9bb4;font:11px ui-monospace}",
            "footer{padding:18px 32px;color:#6b7280;border-top:1px solid #1f2937;font-size:12px}",
            "</style></head><body>",
            "<header><h1>" + html.escape(title) + "</h1>",
            "<div class=sub>" + str(data["crashes"]) + " crashes, "
            + str(len(clusters)) + " clusters  |  " + html.escape(lang_text)
            + "  |  repo " + html.escape(repo_text) + "</div></header>",
            "<main><table><thead><tr><th>#</th><th>count</th><th>cluster</th>"
            "<th>sample message</th><th>lang</th><th>actionable</th><th>first seen</th>"
            "<th>last seen</th><th>root cause</th></tr></thead><tbody>",
            *rows,
            "</tbody></table></main>",
            "<footer>generated " + html.escape(stamp) + " by crashlens 1.0.0</footer>",
            "</body></html>",
        ]
    )


def dump_json(payload: dict[str, object]) -> str:
    """Deterministic JSON: sorted keys, two space indent, trailing newline."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
