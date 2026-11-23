"""Command line interface for crashlens.

Exit codes
    0  analysis completed and a report was produced
    1  nothing matched (no crash records parsed, or no crash hit a recent change)
    2  usage error (bad flag, missing input, unusable repository)
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from collections.abc import Sequence

from . import __version__, heuristics
from .annotate import render_annotation
from .cluster import summary
from .engine import (
    UserError,
    analyse,
    annotate_first,
    blame_since,
    deploy_delta,
    load_crashes,
)
from .fingerprint import fingerprint, normalise_message
from .models import Crash
from .report import cluster_payload, dump_json, render_html, render_terminal, short_time
from .style import Painter, supports_color

EPILOG = "docs: https://github.com/kele-tao/crashlens#readme"


class Parser(argparse.ArgumentParser):
    """Argparse subclass that exits with code 2 and a short hint."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        sys.stderr.write("crashlens: error: " + message + "\n")
        sys.stderr.write("crashlens: hint: run 'crashlens --help' for examples\n")
        raise SystemExit(2)


def _common_options() -> Parser:
    """Options accepted both before and after the subcommand."""
    common = Parser(add_help=False)
    common.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI colour (also honours NO_COLOR)",
    )
    common.add_argument(
        "--encoding",
        default="utf-8",
        help="encoding used to read log files (default: utf-8)",
    )
    return common


def build_parser() -> Parser:
    parser = Parser(
        prog="crashlens",
        description="Turn stack traces into root causes.",
        epilog=EPILOG,
    )
    parser.add_argument("--version", action="version", version="crashlens " + __version__)
    common = _common_options()
    parser.add_argument("--no-color", action="store_true",
                        help="disable ANSI colour (also honours NO_COLOR)")
    parser.add_argument("--encoding", default="utf-8",
                        help="encoding used to read log files (default: utf-8)")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    parse_cmd = sub.add_parser("parse", parents=[common], help="parse tracebacks and print every crash")
    parse_cmd.add_argument("paths", nargs="+", metavar="path", help="log file, directory or - for stdin")
    parse_cmd.add_argument("--json", action="store_true", help="emit machine readable JSON")
    parse_cmd.add_argument("--max-frames", type=int, default=12, help="frames shown per crash (default: 12)")
    parse_cmd.add_argument("--limit", type=int, default=0, help="stop after N crashes (0 = all)")

    cluster_cmd = sub.add_parser(
        "cluster", parents=[common], help="fingerprint, rank and summarise crashes"
    )
    cluster_cmd.add_argument("paths", nargs="+", metavar="path", help="log file, directory or - for stdin")
    cluster_cmd.add_argument("--top", type=int, default=0, help="show only the N highest ranked clusters")
    cluster_cmd.add_argument("--json", action="store_true", help="emit machine readable JSON")
    cluster_cmd.add_argument("--html", metavar="PATH", help="write a self-contained HTML report")
    cluster_cmd.add_argument("--repo", metavar="PATH", help="repository root used to pick actionable frames")
    cluster_cmd.add_argument("--no-hints", action="store_true", help="hide the root-cause heuristics")
    cluster_cmd.add_argument("--min-count", type=int, default=1, help="drop clusters seen fewer than N times")

    annotate_cmd = sub.add_parser(
        "annotate", parents=[common], help="show the failing source line with git blame"
    )
    annotate_cmd.add_argument("paths", nargs="+", metavar="path", help="log file, directory or - for stdin")
    annotate_cmd.add_argument("--repo", metavar="PATH", default=".", help="repository root (default: .)")
    annotate_cmd.add_argument("--context", type=int, default=3, help="source lines around the failure (max 6)")
    annotate_cmd.add_argument("--no-blame", action="store_true", help="skip git blame")
    annotate_cmd.add_argument("--frame", choices=("actionable", "deepest"), default="actionable",
                              help="which frame to annotate (default: actionable)")
    annotate_cmd.add_argument("--raw", action="store_true", help="also print the original traceback")
    annotate_cmd.add_argument("--json", action="store_true", help="emit machine readable JSON")

    blame_cmd = sub.add_parser(
        "blame-since", parents=[common], help="correlate crashes with changes made after a commit"
    )
    blame_cmd.add_argument("since", help="commit sha or ref (for example v1.2.0 or abc1234)")
    blame_cmd.add_argument("paths", nargs="+", metavar="path", help="log file, directory or - for stdin")
    blame_cmd.add_argument("--repo", metavar="PATH", default=".", help="repository root (default: .)")
    blame_cmd.add_argument("--json", action="store_true", help="emit machine readable JSON")

    rules_cmd = sub.add_parser("rules", parents=[common], help="list the root-cause heuristic catalogue")
    rules_cmd.add_argument("--json", action="store_true", help="emit machine readable JSON")
    return parser


def _painter(args: argparse.Namespace) -> Painter:
    if args.no_color:
        return Painter(False)
    return Painter(supports_color(sys.stdout))


def _crashes(args: argparse.Namespace) -> list[Crash]:
    return load_crashes(args.paths, encoding=args.encoding)


def cmd_parse(args: argparse.Namespace) -> int:
    crashes = _crashes(args)
    if not crashes:
        sys.stderr.write("crashlens: no crash records found in " + ", ".join(args.paths) + "\n")
        sys.stderr.write("crashlens: hint: crashlens supports Python, Node.js, Java, Go and Rust tracebacks\n")
        return 1
    limit = args.limit if args.limit and args.limit > 0 else len(crashes)
    selected = crashes[:limit]
    if args.json:
        payload = {
            "tool": "crashlens",
            "version": __version__,
            "crashes": [crash_payload(crash, args.max_frames) for crash in selected],
            "total": len(crashes),
        }
        sys.stdout.write(dump_json(payload))
        return 0
    painter = _painter(args)
    labels = {"python": "Python", "node": "Node.js", "java": "Java", "go": "Go", "rust": "Rust"}
    out: list[str] = []
    out.append(
        painter.bold(str(len(crashes)))
        + " crash"
        + ("" if len(crashes) == 1 else "es")
        + " parsed"
        + (" (showing " + str(len(selected)) + ")" if len(selected) != len(crashes) else "")
    )
    for index, crash in enumerate(selected, 1):
        out.append("")
        out.append(
            painter.cyan("#" + str(index))
            + " "
            + painter.bold(labels.get(crash.language, crash.language))
            + "  "
            + painter.dim(short_time(crash.timestamp))
            + "  "
            + painter.dim(pathlib.Path(crash.source).name if crash.source else "<stdin>")
            + ":"
            + str(crash.header_line)
        )
        out.extend(render_crash(crash, painter, args.max_frames))
    sys.stdout.write("\n".join(out) + "\n")
    return 0


def crash_payload(crash: Crash, max_frames: int) -> dict[str, object]:
    """JSON description of a single crash including its exception chain."""
    return {
        "language": crash.language,
        "source": crash.source,
        "line": crash.header_line,
        "timestamp": crash.timestamp.isoformat() if crash.timestamp else None,
        "exception": normalise_message(crash.exception_type),
        "message": crash.message,
        "fingerprint": crash_fingerprint(crash),
        "chain": [
            {
                "relation": segment.relation,
                "type": segment.exception_type,
                "message": segment.message,
                "frames": [
                    {
                        "function": frame.function,
                        "file": frame.file,
                        "line": frame.line,
                        "column": frame.column,
                    }
                    for frame in segment.frames[:max_frames]
                ],
            }
            for segment in crash.chain
        ],
    }


def crash_fingerprint(crash: Crash) -> str:
    return fingerprint(crash)


def render_crash(crash: Crash, painter: Painter, max_frames: int) -> list[str]:
    """Human readable rendering of one crash with its cause chain."""
    out: list[str] = []
    segments = crash.chain
    for depth, segment in enumerate(segments):
        label = "cause" if depth == 0 else "caused by"
        head = segment.exception_type
        if segment.message:
            head += ": " + normalise_message(segment.message)
        prefix = "  " * (depth + 1)
        if depth == 0:
            out.append(prefix + painter.yellow(label) + "  " + painter.red(painter.bold(head)))
        else:
            out.append(prefix + painter.dim(label) + "  " + head)
        frames = segment.frames[-max_frames:] if max_frames > 0 else segment.frames
        for frame in frames:
            location = frame.file or "<unknown>"
            if frame.line is not None:
                location += ":" + str(frame.line)
            out.append(prefix + "    " + painter.cyan(location) + "  " + painter.dim(frame.function))
    return out


def cmd_cluster(args: argparse.Namespace) -> int:
    analysis = analyse(args.paths, repo_path=args.repo, encoding=args.encoding)
    clusters = analysis.clusters
    if args.min_count > 1:
        clusters = [cluster for cluster in clusters if cluster.count >= args.min_count]
    top = args.top if args.top and args.top > 0 else None
    if args.html:
        html_text = render_html(clusters, analysis.crashes, analysis.repo)
        target = pathlib.Path(args.html)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")
        sys.stderr.write("wrote " + str(target) + " (" + str(target.stat().st_size) + " bytes)\n")
    if args.json:
        payload = {
            "tool": "crashlens",
            "version": __version__,
            "summary": summary_payload(analysis.crashes),
            "repo": str(analysis.repo.root) if analysis.repo else None,
            "clusters": [cluster_payload(cluster, analysis.repo) for cluster in (clusters if top is None else clusters[:top])],
            "omitted_clusters": max(0, len(clusters) - (top or len(clusters))),
        }
        sys.stdout.write(dump_json(payload))
        return 0
    painter = _painter(args)
    if not clusters:
        sys.stderr.write("crashlens: no crash records found in " + ", ".join(args.paths) + "\n")
        return 1
    sys.stdout.write(render_terminal(clusters, analysis.crashes, analysis.repo, painter, limit=top,
                                     show_hints=not args.no_hints))
    return 0


def summary_payload(crashes: list[Crash]) -> dict[str, object]:
    return summary(crashes)


def cmd_annotate(args: argparse.Namespace) -> int:
    annotation = annotate_first(
        args.paths,
        args.repo,
        context=args.context,
        blame=not args.no_blame,
        frame_choice=args.frame,
    )
    if args.json:
        payload = {
            "tool": "crashlens",
            "version": __version__,
            "location": annotation.location,
            "resolved": annotation.resolved,
            "function": annotation.frame.function,
            "exception": annotation.crash.exception_type,
            "message": annotation.crash.message,
            "first_seen": annotation.crash.timestamp.isoformat() if annotation.crash.timestamp else None,
            "blame": (
                {
                    "commit": annotation.blame.commit,
                    "author": annotation.blame.author,
                    "date": annotation.blame.date.isoformat() if annotation.blame.date else None,
                    "summary": annotation.blame.summary,
                }
                if annotation.blame
                else None
            ),
            "source": [
                {"line": line.number, "text": line.text, "target": line.is_target}
                for line in annotation.lines
            ],
        }
        sys.stdout.write(dump_json(payload))
        return 0
    painter = _painter(args)
    sys.stdout.write(render_annotation(annotation, painter, show_raw=args.raw) + "\n")
    return 0


def cmd_blame_since(args: argparse.Namespace) -> int:
    correlation = blame_since(args.paths, args.repo, args.since, encoding=args.encoding)
    painter = _painter(args)
    if args.json:
        sys.stdout.write(dump_json(deploy_delta(correlation)))
        return 0
    out: list[str] = []
    commits = correlation.commits
    out.append(
        painter.bold("deploy window  ")
        + args.since
        + " -> HEAD ("
        + correlation.full_sha[:7]
        + ")"
        + "  "
        + painter.dim(str(len(commits)) + " commit" + ("" if len(commits) == 1 else "s") + ", "
                      + str(len(correlation.changed)) + " file" + ("" if len(correlation.changed) == 1 else "s")
                      + " changed")
    )
    for commit in commits[:8]:
        when = commit.date.strftime("%Y-%m-%d %H:%M") if commit.date else "-"
        out.append(
            "  "
            + painter.yellow(commit.short_sha)
            + " "
            + painter.dim(when)
            + " "
            + commit.author
            + "  "
            + commit.summary
        )
    if len(commits) > 8:
        out.append(painter.dim("  ... " + str(len(commits) - 8) + " more commits"))
    out.append("")
    if not correlation.matched:
        out.append(painter.yellow("no crash frames touch a file changed in this window"))
        out.append(painter.dim("hint: the regression is probably older than " + args.since + "; widen the window"))
        sys.stdout.write("\n".join(out) + "\n")
        return 1
    hits = 0
    for entry in sorted(correlation.changed, key=lambda item: (-len(item.clusters), item.path)):
        if not entry.clusters:
            continue
        first = entry.commits[-1] if entry.commits else None
        when = first.date.strftime("%Y-%m-%d") if first and first.date else "unknown date"
        out.append(
            painter.cyan(entry.path)
            + "  "
            + painter.dim(
                (first.short_sha + " " + when if first else "changed in window")
                + "  "
                + str(len(entry.clusters))
                + " cluster"
                + ("" if len(entry.clusters) == 1 else "s")
            )
        )
        for cluster in entry.clusters:
            sample = cluster.sample
            assert sample is not None
            counts = str(cluster.count) + "x"
            out.append("  " + painter.red(counts.rjust(5)) + "  " + cluster.key + "  " + cluster.label)
            if sample.message:
                out.append("         " + painter.dim(normalise_message(sample.message)[:110]))
        hits += 1
    out.append("")
    out.append(
        painter.bold(str(hits))
        + " changed file"
        + ("" if hits == 1 else "s")
        + (" appears in " if hits == 1 else " appear in ")
        + painter.bold(str(len(correlation.matched)))
        + " cluster"
        + ("" if len(correlation.matched) == 1 else "s")
        + "; "
        + str(len(correlation.unmatched))
        + " cluster"
        + ("" if len(correlation.unmatched) == 1 else "s")
        + " unrelated to this window"
    )
    sys.stdout.write("\n".join(out) + "\n")
    return 0


def cmd_rules(args: argparse.Namespace) -> int:
    rules = heuristics.catalogue()
    if args.json:
        sys.stdout.write(dump_json({"rules": rules, "total": len(rules)}))
        return 0
    painter = _painter(args)
    out = [painter.bold(str(len(rules))) + " root-cause rules"]
    for rule in rules:
        out.append("  " + painter.cyan(rule["rule"].ljust(18)) + " " + rule["exception"])
        if rule["message"]:
            out.append("  " + " " * 18 + " " + painter.dim("message: " + rule["message"]))
    sys.stdout.write("\n".join(out) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    handlers = {
        "parse": cmd_parse,
        "cluster": cmd_cluster,
        "annotate": cmd_annotate,
        "blame-since": cmd_blame_since,
        "rules": cmd_rules,
    }
    handler = handlers[args.command]
    try:
        return handler(args)
    except UserError as exc:
        sys.stderr.write("crashlens: error: " + str(exc) + "\n")
        return 2
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        sys.stderr.write("crashlens: interrupted\n")
        return 130


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())
