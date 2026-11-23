"""Typed data model shared by the parser, clustering and reporting layers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

LANGUAGE_LABELS = {
    "python": "Python",
    "node": "Node.js",
    "java": "Java",
    "go": "Go",
    "rust": "Rust",
}


@dataclass(frozen=True)
class Frame:
    """One stack frame, normalised across runtimes.

    `file` is whatever the runtime printed (absolute, relative or a vendor path
    such as `node:internal/process/task_queues`).  Deciding whether a frame is
    project owned needs a repository root, so that lives in `analysis.py`.
    """

    function: str
    file: str | None = None
    line: int | None = None
    column: int | None = None

    @property
    def location(self) -> str:
        """Human readable `file:line (function)` description."""
        if not self.file:
            return self.function
        if self.line is None:
            return self.file + " (" + self.function + ")"
        return self.file + ":" + str(self.line) + " (" + self.function + ")"


@dataclass(frozen=True)
class Segment:
    """One link of an exception chain.

    `segments[0]` is always the exception that actually reached the top level
    (the one a user sees last).  Later segments are its causes, in order.
    `relation` describes why this segment appears in the chain, i.e. how the
    exception *before* it relates to it: `"cause"` (Python
    `raise ... from ...`, Java `Caused by:`) or `"context"` (Python
    `during handling of the above exception`).  `None` marks the primary
    exception, which has nothing before it.
    """

    exception_type: str
    message: str = ""
    frames: tuple[Frame, ...] = ()
    relation: str | None = None


@dataclass
class Crash:
    """A single parsed crash: one traceback, panic or exception record."""

    language: str
    segments: list[Segment]
    raw: str
    timestamp: datetime | None = None
    source: str = ""
    header_line: int = 0

    @property
    def primary(self) -> Segment:
        return self.segments[0]

    @property
    def frames(self) -> tuple[Frame, ...]:
        """Frames of the exception that reached the top level."""
        return self.primary.frames

    @property
    def all_frames(self) -> tuple[Frame, ...]:
        """Frames from every segment, top-level exception first."""
        out: list[Frame] = []
        for segment in self.segments:
            out.extend(segment.frames)
        return tuple(out)

    @property
    def exception_type(self) -> str:
        return self.primary.exception_type

    @property
    def message(self) -> str:
        return self.primary.message

    @property
    def chain(self) -> list[Segment]:
        """Cause chain in root-cause-first order (for display)."""
        return list(reversed(self.segments))

    @property
    def chain_types(self) -> list[str]:
        return [segment.exception_type for segment in self.chain]

    @property
    def site_frame(self) -> Frame | None:
        """The frame where the runtime actually stopped.

        Every parser normalises its frames to outermost-first, so the last
        frame is the innermost call site.  Frames without a source location
        (Node prints native callbacks as "at Array.map (anonymous)") are
        skipped so the location stays useful.
        """
        for frame in reversed(self.frames):
            if frame.file:
                return frame
        return self.frames[-1] if self.frames else None

    @property
    def deepest_frame(self) -> Frame | None:
        return self.frames[-1] if self.frames else None

    def signature(self) -> str:
        """`KeyError at app/pipeline.py:32` style short description."""
        frame = self.site_frame
        if frame is None:
            return self.exception_type
        where = frame.file or frame.function
        if frame.line is not None:
            where += ":" + str(frame.line)
        return self.exception_type + " at " + where

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.signature()
