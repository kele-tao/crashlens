"""Parsers for Python, Node.js, Java, Go and Rust crash records.

The public entry points are parse_text and parse_file.  Everything is line
oriented and regex based: no language runtime is required, so a 10k line
production log is parsed in a single pass with no external dependencies.
"""

from __future__ import annotations

import pathlib
import re
from datetime import datetime

from .models import Crash, Frame, Segment

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

TIMESTAMP_RE = re.compile(
    r"^\[?(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?"
    r"(?:Z|[+-]\d{2}:?\d{2})?)\]?(?:\s+|$)"
)
LEVEL_RE = re.compile(r"^(?:TRACE|DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL|FATAL)\b[:\-]?\s?")

PY_HEADER = "Traceback (most recent call last):"
PY_FRAME_RE = re.compile(r'^\s+File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+?)\s*$')
PY_EXC_RE = re.compile(r"^(?P<type>[A-Za-z_][\w.]*)(?::\s?(?P<msg>.*))?$")
PY_CHAIN_RE = re.compile(
    r"^(?:The above exception was the direct cause of the following exception:"
    r"|During handling of the above exception, another exception occurred:)\s*$"
)

JAVA_HEADER_RE = re.compile(
    r'^(?:Exception in thread "[^"]*"\s+)?(?:Caused by: |Suppressed: )?'
    r"(?P<type>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+)(?::\s?(?P<msg>.*))?$"
)
JAVA_FRAME_RE = re.compile(r"^\s+at (?P<func>[^()\s]+)\((?P<rest>[^()]*)\)\s*$")
JAVA_MORE_RE = re.compile(r"^\s+\.\.\. \d+ (?:more|common frames omitted)\s*$")

NODE_HEADER_RE = re.compile(
    r"^(?:Uncaught\s+)?(?P<type>[A-Za-z_$][\w$]*(?:Error|Exception))(?::\s?(?P<msg>.*))?$"
)
NODE_FRAME_RE = re.compile(
    r"^\s+at (?:async )?(?:(?P<func>[^()]+?) )?\(?(?P<file>[^()]+?):"
    r"(?P<line>\d+):(?P<col>\d+)\)?\s*$"
)
NODE_BARE_FRAME_RE = re.compile(r"^\s+at (?P<func>\S.*?)\s*$")

GO_PANIC_RE = re.compile(r"^panic: (?P<msg>.*)$")
GO_FUNC_RE = re.compile(r"^(?:created by )?[A-Za-z_$][\w$./*\[\]]*(?:\(\*?[\w.]+\))?[\w.$]*\(.*\)$")
GO_LOC_RE = re.compile(r"^\t+(?P<file>[^\s:][^:]*\.go):(?P<line>\d+)(?: \+0x[0-9a-f]+)?$")

RUST_PANIC_RE = re.compile(
    r"^thread '(?P<thread>[^']*)' panicked at (?:'(?P<msg>[^']*)',?\s*)?"
    r"(?P<file>[^\s:][^:]*):(?P<line>\d+):(?P<col>\d+):?$"
)
RUST_BT_FRAME_RE = re.compile(r"^\s*(?P<idx>\d+):\s+(?P<func>\S+)\s*$")
RUST_BT_LOC_RE = re.compile(r"^\s+at (?P<file>[^\s:][^:]*):(?P<line>\d+):(?P<col>\d+)\s*$")

FORMATS = ("python", "node", "java", "go", "rust")


def strip_ansi(text: str) -> str:
    """Remove ANSI colour escapes so parsers see plain text."""
    return ANSI_RE.sub("", text)


def parse_timestamp(token: str) -> datetime | None:
    """Parse the timestamp prefixes common in log files."""
    clean = token.replace(",", ".")
    if clean.endswith("Z"):
        clean = clean[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(clean)
    except ValueError:
        return None


class _Line:
    __slots__ = ("text", "timestamp")

    def __init__(self, text: str, timestamp: datetime | None) -> None:
        self.text = text
        self.timestamp = timestamp


def _prepare(text: str) -> list[_Line]:
    """Normalise newlines, strip ANSI codes and log prefixes from every line.

    Traceback lines never carry their own timestamp, so the timestamp of the
    most recent stamped log line is carried forward; that is what makes
    first/last seen and recency ranking possible on mixed log files.
    """
    text = strip_ansi(text.replace("\r\n", "\n").replace("\r", "\n"))
    out: list[_Line] = []
    last_seen: datetime | None = None
    for raw in text.split("\n"):
        line = raw
        stamp: datetime | None = None
        match = TIMESTAMP_RE.match(raw)
        if match:
            stamp = parse_timestamp(match.group("ts"))
            line = raw[match.end():]
            level = LEVEL_RE.match(line)
            if level:
                line = line[level.end():]
        out.append(_Line(line, stamp))
        if stamp is not None:
            last_seen = stamp
    carried: datetime | None = None
    for entry in out:
        if entry.timestamp is not None:
            carried = entry.timestamp
        else:
            entry.timestamp = carried
    if carried is None:
        for entry in out:
            entry.timestamp = last_seen
    return out


def _is_python_start(text: str) -> bool:
    return text.startswith(PY_HEADER)


def _python_end(lines: list[_Line], start: int) -> int:
    index = start + 1
    total = len(lines)
    while index < total:
        text = lines[index].text
        if not text.strip():
            look = index + 1
            while look < total and not lines[look].text.strip():
                look += 1
            if look < total and (
                PY_CHAIN_RE.match(lines[look].text.strip()) or _is_python_start(lines[look].text)
            ):
                index = look
                continue
            break
        if text[0].isspace():
            index += 1
            continue
        stripped = text.strip()
        if _is_python_start(text) or PY_CHAIN_RE.match(stripped):
            index += 1
            continue
        if PY_EXC_RE.match(text):
            index += 1
            look = index
            while look < total and not lines[look].text.strip():
                look += 1
            if look < total and PY_CHAIN_RE.match(lines[look].text.strip()):
                index = look
                continue
            break
        break
    return index


def _java_like_end(lines: list[_Line], start: int, kind: str) -> int:
    index = start + 1
    total = len(lines)
    while index < total:
        text = lines[index].text
        if not text.strip():
            look = index + 1
            while look < total and not lines[look].text.strip():
                look += 1
            if look < total and _is_java_continuation(lines[look].text, kind):
                index = look
                continue
            break
        if _is_java_continuation(text, kind):
            index += 1
            continue
        if kind == "java" and _is_java_header(text):
            index += 1
            continue
        break
    return index


def _is_java_header(text: str) -> bool:
    if not text or text[0].isspace():
        return False
    return bool(JAVA_HEADER_RE.match(text))


def _is_java_continuation(text: str, kind: str) -> bool:
    if JAVA_MORE_RE.match(text) or JAVA_FRAME_RE.match(text):
        return True
    if kind == "java" and (text.startswith("Caused by:") or text.startswith("Suppressed:")):
        return True
    if kind == "node":
        return bool(NODE_FRAME_RE.match(text) or NODE_BARE_FRAME_RE.match(text))
    return False


def _go_end(lines: list[_Line], start: int) -> int:
    index = start + 1
    total = len(lines)
    seen_frame = False
    while index < total:
        text = lines[index].text
        stripped = text.strip()
        if not stripped:
            if seen_frame:
                break
            index += 1
            continue
        if stripped.startswith("exit status"):
            break
        if stripped.startswith("[signal ") or stripped.startswith("panic: "):
            index += 1
            continue
        if stripped.startswith("goroutine ") or stripped.startswith("created by "):
            index += 1
            continue
        if GO_LOC_RE.match(text):
            seen_frame = True
            index += 1
            continue
        if not text[0].isspace() and GO_FUNC_RE.match(text):
            index += 1
            continue
        break
    return index


def _rust_end(lines: list[_Line], start: int) -> int:
    index = start + 1
    total = len(lines)
    while index < total:
        text = lines[index].text
        stripped = text.strip()
        if not stripped:
            look = index + 1
            while look < total and not lines[look].text.strip():
                look += 1
            if look < total and RUST_BT_FRAME_RE.match(lines[look].text):
                index = look
                continue
            break
        if (
            stripped.startswith("stack backtrace:")
            or stripped.startswith("note: ")
            or RUST_BT_FRAME_RE.match(text)
            or RUST_BT_LOC_RE.match(text)
        ):
            index += 1
            continue
        if index == start + 1:
            index += 1
            continue
        break
    return index


def _classify_java_or_node(lines: list[_Line], index: int) -> str | None:
    header = JAVA_HEADER_RE.match(lines[index].text)
    if header and "." in header.group("type"):
        return "java"
    for look in range(index + 1, min(index + 6, len(lines))):
        text = lines[look].text
        if ".java:" in text:
            return "java"
        if re.search(r"\.(?:js|mjs|cjs|ts|tsx|jsx):\d+", text) or "node:" in text:
            return "node"
    return "node" if header else None


def _detect_start(lines: list[_Line], index: int) -> str | None:
    text = lines[index].text
    if not text or text[0].isspace():
        return None
    if _is_python_start(text):
        return "python"
    if GO_PANIC_RE.match(text):
        return "go"
    if RUST_PANIC_RE.match(text):
        return "rust"
    if text.startswith('Exception in thread "') or text.startswith("Caused by:"):
        return "java"
    if _is_java_header(text):
        return _classify_java_or_node(lines, index)
    if NODE_HEADER_RE.match(text):
        return "node"
    return None


def _block_end(fmt: str, lines: list[_Line], start: int) -> int:
    if fmt == "python":
        return _python_end(lines, start)
    if fmt in {"java", "node"}:
        return _java_like_end(lines, start, fmt)
    if fmt == "go":
        return _go_end(lines, start)
    return _rust_end(lines, start)


def _parse_python_lines(lines: list[str]) -> list[Segment]:
    segs: list[Segment] = []
    frames: list[Frame] = []
    relation: str | None = None
    for text in lines:
        if _is_python_start(text):
            frames = []
            continue
        frame_match = PY_FRAME_RE.match(text)
        if frame_match:
            frames.append(
                Frame(
                    function=frame_match.group("func").strip(),
                    file=frame_match.group("file"),
                    line=int(frame_match.group("line")),
                )
            )
            continue
        if PY_CHAIN_RE.match(text.strip()):
            relation = "cause" if "direct cause" in text else "context"
            continue
        if text and not text[0].isspace():
            exc = PY_EXC_RE.match(text)
            if exc:
                segs.append(
                    Segment(
                        exception_type=exc.group("type"),
                        message=(exc.group("msg") or "").strip(),
                        frames=tuple(frames),
                        relation=relation if segs else None,
                    )
                )
                relation = None
                frames = []
    ordered = list(reversed(segs))
    # The "during handling / direct cause" markers describe how the exception
    # *before* the marker relates to the one after it.  Once the list is
    # reversed the marker belongs to the cause segment, i.e. the segment that
    # explains the one above it.
    markers = [segment.relation for segment in ordered]
    fixed: list[Segment] = [ordered[0]] if ordered else []
    for index in range(1, len(ordered)):
        assert ordered[index] is not None
        fixed.append(
            Segment(
                exception_type=ordered[index].exception_type,
                message=ordered[index].message,
                frames=ordered[index].frames,
                relation=markers[index - 1] or "cause",
            )
        )
    return fixed


def _parse_java_lines(lines: list[str]) -> list[Segment]:
    segs: list[Segment] = []
    frames: list[Frame] = []
    current_type: str | None = None
    current_msg = ""
    relation: str | None = None

    def flush() -> None:
        nonlocal frames, current_type, current_msg, relation
        if current_type is not None:
            segs.append(
                Segment(
                    exception_type=current_type,
                    message=current_msg,
                    frames=tuple(frames),
                    relation=relation if segs else None,
                )
            )
        frames = []
        current_type = None
        current_msg = ""
        relation = None

    for text in lines:
        frame_match = JAVA_FRAME_RE.match(text)
        if frame_match:
            rest = frame_match.group("rest").strip()
            file_part = rest
            line_no: int | None = None
            if ":" in rest:
                head, tail = rest.rsplit(":", 1)
                if tail.isdigit():
                    file_part = head
                    line_no = int(tail)
            frames.append(
                Frame(function=frame_match.group("func"), file=file_part or None, line=line_no)
            )
            continue
        if JAVA_MORE_RE.match(text):
            continue
        stripped = text.strip()
        if stripped.startswith("Caused by:") or stripped.startswith("Suppressed:"):
            flush()
            relation = "cause" if stripped.startswith("Caused by:") else "context"
            header = JAVA_HEADER_RE.match(stripped)
            if header:
                current_type = header.group("type")
                current_msg = (header.group("msg") or "").strip()
            continue
        header = JAVA_HEADER_RE.match(text)
        if header:
            if current_type is not None:
                flush()
            current_type = header.group("type")
            current_msg = (header.group("msg") or "").strip()
    flush()
    # The first header is the exception a user saw, later headers are causes,
    # so file order is already primary-first.  Java prints the innermost frame
    # first though, so frames are reversed into the outermost-first convention
    # used by every parser.
    return [
        Segment(
            exception_type=segment.exception_type,
            message=segment.message,
            frames=tuple(reversed(segment.frames)),
            relation=segment.relation,
        )
        for segment in segs
    ]


def _parse_node_lines(lines: list[str]) -> list[Segment]:
    segs: list[Segment] = []
    frames: list[Frame] = []
    current_type: str | None = None
    current_msg = ""

    def flush() -> None:
        nonlocal frames, current_type, current_msg
        if current_type is not None:
            segs.append(
                Segment(exception_type=current_type, message=current_msg, frames=tuple(frames))
            )
        frames = []
        current_type = None
        current_msg = ""

    for text in lines:
        frame_match = NODE_FRAME_RE.match(text)
        if frame_match:
            frames.append(
                Frame(
                    function=(frame_match.group("func") or "<anonymous>").strip(),
                    file=frame_match.group("file").strip(),
                    line=int(frame_match.group("line")),
                    column=int(frame_match.group("col")),
                )
            )
            continue
        bare_match = NODE_BARE_FRAME_RE.match(text)
        if bare_match:
            name = bare_match.group("func").strip().replace(" (<anonymous>)", "")
            frames.append(Frame(function=name))
            continue
        header = NODE_HEADER_RE.match(text)
        if header:
            if current_type is not None:
                flush()
            current_type = header.group("type")
            current_msg = (header.group("msg") or "").strip()
    flush()
    # Node prints innermost frame first; normalise to outermost first.
    return [
        Segment(
            exception_type=segment.exception_type,
            message=segment.message,
            frames=tuple(reversed(segment.frames)),
            relation=segment.relation,
        )
        for segment in segs
    ]


def _parse_go_lines(lines: list[str]) -> list[Segment]:
    frames: list[Frame] = []
    message = ""
    functions: list[str] = [""] * len(lines)
    for index, text in enumerate(lines):
        stripped = text.strip()
        if GO_FUNC_RE.match(stripped) and not GO_LOC_RE.match(text):
            # Strip only the trailing argument list so method receivers such as
            # (*Worker) survive: acme/queue.(*Worker).Run(0xc0000a4000)
            functions[index] = re.sub(r"\([^()]*\)$", "", stripped).strip()
        elif stripped.startswith("created by "):
            functions[index] = stripped
    for index, text in enumerate(lines):
        panic = GO_PANIC_RE.match(text)
        if panic:
            message = panic.group("msg").strip()
            continue
        location = GO_LOC_RE.match(text)
        if location:
            function = ""
            for back in range(index - 1, max(index - 3, -1), -1):
                if functions[back]:
                    function = functions[back]
                    break
            frames.append(
                Frame(
                    function=function or "<unknown>",
                    file=location.group("file"),
                    line=int(location.group("line")),
                )
            )
    # Go prints the crashing frame first and its callers below it; reversing
    # gives the outermost-first convention used by every parser.
    return [Segment(exception_type="panic", message=message, frames=tuple(reversed(frames)))]


def _parse_rust_lines(lines: list[str]) -> list[Segment]:
    frames: list[Frame] = []
    message_parts: list[str] = []
    panic = RUST_PANIC_RE.match(lines[0]) if lines else None
    location_frame: Frame | None = None
    if panic:
        if panic.group("msg"):
            message_parts.append(panic.group("msg"))
        location_frame = Frame(
            function="<panic>",
            file=panic.group("file"),
            line=int(panic.group("line")),
            column=int(panic.group("col")),
        )
    pending: str | None = None
    for text in lines[1:]:
        stripped = text.strip()
        if stripped.startswith("stack backtrace:") or stripped.startswith("note: "):
            continue
        frame_match = RUST_BT_FRAME_RE.match(text)
        if frame_match:
            pending = frame_match.group("func")
            continue
        loc_match = RUST_BT_LOC_RE.match(text)
        if loc_match:
            frames.append(
                Frame(
                    function=pending or "<unknown>",
                    file=loc_match.group("file"),
                    line=int(loc_match.group("line")),
                    column=int(loc_match.group("col")),
                )
            )
            pending = None
            continue
        if not stripped:
            continue
        if not frames and not location_frame and pending is None:
            message_parts.append(stripped)
    if not frames and location_frame is not None:
        frames.append(location_frame)
    message = " ".join(part for part in message_parts if part).strip()
    # A Rust backtrace lists frame 0 (rust_begin_unwind) first and the user's
    # code last, which is already the outermost-first convention.
    return [Segment(exception_type="panic", message=message, frames=tuple(frames))]


def parse_text(text: str, source: str = "") -> list[Crash]:
    """Parse every crash record found in *text*.

    Returns crashes in file order.  Unknown or malformed blocks are skipped
    rather than raising: a production log is usually a mix of noise and
    tracebacks, and a parser that explodes on noise is useless.
    """
    lines = _prepare(text)
    crashes: list[Crash] = []
    index = 0
    total = len(lines)
    while index < total:
        fmt = _detect_start(lines, index)
        if fmt is None:
            index += 1
            continue
        end = max(_block_end(fmt, lines, index), index + 1)
        block = [entry.text for entry in lines[index:end]]
        while block and not block[-1].strip():
            block.pop()
        if not block:
            index = end
            continue
        if fmt == "python":
            segments = _parse_python_lines(block)
        elif fmt == "java":
            segments = _parse_java_lines(block)
        elif fmt == "node":
            segments = _parse_node_lines(block)
        elif fmt == "go":
            segments = _parse_go_lines(block)
        else:
            segments = _parse_rust_lines(block)
        segments = [segment for segment in segments if segment.exception_type]
        if segments:
            crashes.append(
                Crash(
                    language=fmt,
                    segments=segments,
                    raw="\n".join(block),
                    timestamp=lines[index].timestamp,
                    source=source,
                    header_line=index + 1,
                )
            )
        index = end
    return crashes


def parse_file(path: str | pathlib.Path, encoding: str = "utf-8") -> list[Crash]:
    """Read *path* and parse every crash record it contains.

    Raises FileNotFoundError for a missing file and OSError when the file
    cannot be read; the CLI turns those into friendly messages.
    """
    file_path = pathlib.Path(path)
    text = file_path.read_text(encoding=encoding, errors="replace")
    return parse_text(text, source=str(file_path))


def parse_paths(paths: list[str | pathlib.Path]) -> list[Crash]:
    """Parse files, walking directories for log-like files."""
    suffixes = {".log", ".txt", ".out", ".err", ".trace"}
    crashes: list[Crash] = []
    for item in paths:
        target = pathlib.Path(item)
        if target.is_dir():
            for child in sorted(p for p in target.rglob("*") if p.is_file()):
                if child.suffix.lower() not in suffixes:
                    continue
                crashes.extend(parse_file(child))
        else:
            crashes.extend(parse_file(target))
    return crashes
