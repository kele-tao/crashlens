"""Source annotation: show the failing line with context and git blame."""

from __future__ import annotations

from dataclasses import dataclass

from .gitinfo import Blame, blame_line
from .models import Crash, Frame
from .repo import Repo
from .style import Painter

MAX_CONTEXT = 6


@dataclass(frozen=True)
class ContextLine:
    """One rendered source line."""

    number: int
    text: str
    is_target: bool


@dataclass
class Annotation:
    """Everything the renderer needs to explain one crash location."""

    crash: Crash
    frame: Frame
    relative_path: str | None
    lines: list[ContextLine]
    blame: Blame | None
    total_lines: int
    resolved: bool
    segment_type: str = ""

    @property
    def marker(self) -> str:
        """Exception type that the annotated frame raised."""
        return self.segment_type or self.crash.exception_type

    @property
    def location(self) -> str:
        if self.relative_path and self.frame.line is not None:
            return self.relative_path + ":" + str(self.frame.line)
        return self.frame.location


def clamp_context(context: int) -> int:
    """Keep the context window printable and the memory cost bounded."""
    if context < 0:
        return 0
    return min(context, MAX_CONTEXT)


def annotate_crash(
    crash: Crash,
    repo: Repo | None,
    context: int = 3,
    use_blame: bool = True,
    frame: Frame | None = None,
) -> Annotation:
    """Build an annotation for the most useful frame of *crash*."""
    context = clamp_context(context)
    target = frame if frame is not None else crash.deepest_frame
    if target is None:
        return Annotation(crash=crash, frame=Frame("<unknown>"), relative_path=None,
                          lines=[], blame=None, total_lines=0, resolved=False)
    if repo is None:
        return Annotation(crash=crash, frame=target, relative_path=None, lines=[],
                          blame=None, total_lines=0, resolved=False)
    path = repo.locate(target.file)
    if path is None or target.line is None:
        return Annotation(crash=crash, frame=target, relative_path=None, lines=[],
                          blame=None, total_lines=0, resolved=False)
    source = repo.read_lines(path)
    if not source:
        return Annotation(crash=crash, frame=target, relative_path=None, lines=[],
                          blame=None, total_lines=0, resolved=False)
    total = len(source)
    line_no = max(1, min(target.line, total))
    start = max(1, line_no - context)
    end = min(total, line_no + context)
    lines = [
        ContextLine(number=number, text=source[number - 1], is_target=number == line_no)
        for number in range(start, end + 1)
    ]
    relative = repo.relative(path)
    segment_type = crash.exception_type
    for segment in crash.chain:
        if target in segment.frames:
            segment_type = segment.exception_type
            break
    blame: Blame | None = None
    if use_blame and repo.is_git():
        blame = blame_line(repo.root, relative, line_no)
    return Annotation(
        crash=crash,
        frame=target,
        relative_path=relative,
        lines=lines,
        blame=blame,
        total_lines=total,
        resolved=True,
        segment_type=segment_type,
    )


def render_annotation(annotation: Annotation, painter: Painter, show_raw: bool = False) -> str:
    """Human readable block for one annotated crash.

    The arrows, the blame line and the 'days before the first crash' delta are
    what turn a stack trace into a deploy question.
    """
    crash = annotation.crash
    out: list[str] = []
    header = crash.exception_type
    if crash.message:
        header += ": " + crash.message
    out.append(painter.paint("crash", "\x1b[1m", "\x1b[36m") + "  " + painter.red(header))
    if len(crash.segments) > 1:
        chain = " -> ".join(crash.chain_types)
        relations = [segment.relation for segment in crash.chain[1:]]
        suffix = "  (" + ", ".join(r for r in relations if r) + ")" if any(relations) else ""
        out.append("chain  " + chain + suffix)
    out.append("where  " + annotation.location + "  in  " + annotation.frame.function)
    out.append("")
    if not annotation.resolved:
        out.append(painter.yellow("source not found: ") + (annotation.frame.file or "<unknown>"))
        out.append("hint: pass --repo pointing at the checkout that produced this traceback")
    else:
        width = len(str(annotation.lines[-1].number)) if annotation.lines else 1
        for line in annotation.lines:
            number = str(line.number).rjust(width)
            if line.is_target:
                out.append(
                    painter.paint(">", "\x1b[1m", "\x1b[33m")
                    + " "
                    + painter.yellow(number)
                    + " | "
                    + painter.paint(line.text, "\x1b[1m")
                    + "   <-- " + painter.red(annotation.marker)
                )
            else:
                out.append("  " + painter.dim(number) + " | " + line.text)
    if annotation.blame is not None:
        out.append("")
        out.append(painter.magenta("blame   ") + annotation.blame.describe())
        delta = days_between(annotation.blame, crash.timestamp)
        if delta is not None and delta >= 0:
            out.append(
                painter.magenta("timing  ")
                + "first seen "
                + str(crash.timestamp)
                + " ("
                + str(delta)
                + " day"
                + ("s" if delta != 1 else "")
                + " after that commit)"
            )
    if show_raw:
        out.append("")
        out.append(painter.dim("raw traceback"))
        for line in crash.raw.splitlines():
            out.append("  " + painter.dim(line))
    return "\n".join(out)


def days_between(blame: Blame, timestamp) -> int | None:
    """Whole days between the blamed commit and the crash, or None."""
    if blame.date is None or timestamp is None:
        return None
    try:
        commit_day = blame.date.date()
        crash_day = timestamp.date()
    except AttributeError:  # pragma: no cover - defensive
        return None
    return (crash_day - commit_day).days
