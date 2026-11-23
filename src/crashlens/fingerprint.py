"""Crash normalisation, fingerprinting and actionable-frame selection."""

from __future__ import annotations

import hashlib
import re

from .models import Crash, Frame, Segment
from .repo import Repo, normalise_path

FRAME_BUDGET = 6

HEX_RE = re.compile(r"0x[0-9a-fA-F]+|\b[0-9a-f]{7,40}\b")
DIGITS_RE = re.compile(r"\d+")
LAMBDA_RE = re.compile(r"lambda\$[\w$]*\$\d+")
TEMPLATE_RE = re.compile(r"<.*?>")


def normalise_function(name: str) -> str:
    """Collapse per-run noise in function names.

    Java lambdas carry a counter, Go closures carry an address, Python
    comprehensions carry a line number.  None of that should split a cluster.
    """
    out = name.strip()
    out = LAMBDA_RE.sub("lambda", out)
    out = HEX_RE.sub("<hex>", out)
    out = DIGITS_RE.sub("#", out)
    out = out.replace("<hex>", "0xADDR")
    out = TEMPLATE_RE.sub("<T>", out)
    return out or "<unknown>"


def normalise_type(name: str) -> str:
    """Keep only the last component of a fully qualified exception name."""
    return name.rsplit(".", 1)[-1].strip() or "Exception"


def normalise_message(message: str) -> str:
    """Remove values that differ between occurrences of the same bug."""
    out = message.strip()
    out = re.sub(r"(['\"])(?:(?!\1).){1,200}?\1", "<value>", out)
    out = re.sub(r"(?<![\w])[\w.~-]*[/\\][\w./~\\-]+", "<path>", out)
    out = re.sub(r"0x[0-9a-fA-F]+", "0xADDR", out)
    out = re.sub(r"\b[0-9a-f]{8,}\b", "<hash>", out)
    out = re.sub(r"\b\d+\b", "#", out)
    out = re.sub(r"\s+", " ", out)
    return out[:160]


def _frame_key(frame_file: str | None, function: str) -> str:
    where = normalise_path(frame_file) if frame_file else ""
    return normalise_function(function) + "@" + where


def _segment_key(segment: Segment) -> str:
    frames = [_frame_key(frame.file, frame.function) for frame in segment.frames[:FRAME_BUDGET]]
    return normalise_type(segment.exception_type) + "[" + ",".join(frames) + "]"


def fingerprint_parts(crash: Crash) -> tuple[str, ...]:
    """Ordered, human readable components hashed into the fingerprint."""
    parts = [crash.language]
    for segment in crash.chain:
        parts.append(_segment_key(segment))
    return tuple(parts)


def fingerprint(crash: Crash) -> str:
    """Stable 12 hex character id for a crash shape.

    Two crashes share a fingerprint when their language, exception chain and
    normalised call sites match.  Line numbers, addresses, temp paths and
    numeric message values are excluded on purpose.
    """
    joined = "|".join(fingerprint_parts(crash))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def fingerprint_label(crash: Crash) -> str:
    """Short description such as 'KeyError at app/pipeline.py'."""
    frame = crash.site_frame
    where = normalise_path(frame.file) if frame and frame.file else "<unknown>"
    return normalise_type(crash.exception_type) + " at " + where


def actionable_frame(crash: Crash, repo: Repo | None = None) -> Frame | None:
    """Deepest project-owned frame of the chain, searched root cause first.

    A traceback's primary exception is usually a wrapper: the HTTP handler
    re-raises "order enrichment failed" around the KeyError that actually
    broke.  Searching the chain from the root cause outwards therefore lands
    on the line worth opening, and the innermost owned frame of that segment
    wins because the outer frames are the framework boundary.  Without a
    usable repository the innermost frame of the primary exception is used.
    """
    if repo is not None:
        for segment in crash.chain:
            for frame in reversed(segment.frames):
                if repo.is_owned(frame):
                    return frame
    return crash.site_frame


def frame_index(crash: Crash, frame: Frame) -> int:
    """Position of *frame* in the flattened chain, or -1."""
    for index, candidate in enumerate(crash.all_frames):
        if candidate == frame:
            return index
    return -1
