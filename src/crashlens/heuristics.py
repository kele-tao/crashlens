"""Root-cause heuristics: turn a crash shape into a concrete next step.

Each rule is deliberately narrow and cites the evidence it matched, so the
output is a hint a human can verify, not an oracle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Crash

MAX_STEPS = 2


@dataclass(frozen=True)
class Diagnosis:
    """One plausible root cause with the evidence that triggered it."""

    rule: str
    title: str
    next_step: str
    confidence: str = "medium"

    def as_dict(self) -> dict[str, str]:
        return {
            "rule": self.rule,
            "title": self.title,
            "next_step": self.next_step,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class Rule:
    name: str
    title: str
    next_step: str
    exception_re: str
    message_re: str = ""
    confidence: str = "medium"

    def matches(self, crash: Crash) -> bool:
        types = " ".join(crash.chain_types)
        if not re.search(self.exception_re, types, re.IGNORECASE):
            return False
        if not self.message_re:
            return True
        text = crash.message + " " + crash.raw[:4000]
        return bool(re.search(self.message_re, text, re.IGNORECASE))


RULES: tuple[Rule, ...] = (
    Rule(
        name="none-optional",
        title="A value assumed to be present came back None",
        next_step=(
            "Guard the optional value before use: default it at the boundary, or raise "
            "a typed error carrying the request id instead of letting None travel "
            "three frames."
        ),
        exception_re=r"AttributeError|TypeError|NullPointerException|nil pointer",
        message_re=r"NoneType|None|null|nil pointer|Cannot read propert",
        confidence="high",
    ),
    Rule(
        name="missing-key",
        title="Code indexes a mapping key that the payload does not contain",
        next_step=(
            "Validate the payload against an explicit schema at the parse boundary, then "
            "read it through dict.get or a dataclass so absence becomes a named error."
        ),
        exception_re=r"KeyError|NoSuchElementException",
    ),
    Rule(
        name="json-shape",
        title="Parsed JSON does not have the shape the code expects",
        next_step=(
            "Log the raw body once at the parse site and assert the top-level type and "
            "required keys before descending into it."
        ),
        exception_re=r"JSONDecodeError|JsonParseException|ValueError|SyntaxError|Unexpected token",
        message_re=r"json|unexpected token|expecting value|unexpected end",
        confidence="high",
    ),
    Rule(
        name="transient-network",
        title="A remote peer reset or timed out the connection",
        next_step=(
            "Treat it as transient: retry with jittered backoff and a connect/read "
            "timeout, and alert only after N failures inside a time window."
        ),
        exception_re=(
            r"ConnectionResetError|ConnectionError|TimeoutError|SocketTimeout|"
            r"ConnectTimeout|ECONNRESET|ETIMEDOUT|ECONNREFUSED|EPIPE|Dial tcp"
        ),
        message_re=r"reset by peer|timed out|timeout|connection refused|broken pipe|no route",
        confidence="high",
    ),
    Rule(
        name="memory",
        title="The process ran out of memory",
        next_step=(
            "Bound the allocation: stream instead of materialising, cap the batch size "
            "and set a container memory limit so the OOM killer is not the monitor."
        ),
        exception_re=r"MemoryError|OutOfMemoryError|AllocationError",
        message_re=r"memory|cannot allocate|out of memory|heap space",
        confidence="high",
    ),
    Rule(
        name="recursion",
        title="The call graph recursed without a base case",
        next_step=(
            "Convert the recursion to an explicit stack, or add a depth guard that fails "
            "with the input that caused it."
        ),
        exception_re=r"RecursionError|StackOverflowError",
        message_re=r"recursion|stack overflow|stack size",
        confidence="high",
    ),
    Rule(
        name="pandas-column",
        title="A pandas column referenced by name is missing from the frame",
        next_step=(
            "Validate df.columns before the transform (or df.reindex(columns=expected)) "
            "and fail with the missing column names."
        ),
        exception_re=r"KeyError|ValueError|AttributeError",
        message_re=r"column|not in index|DataFrame",
        confidence="high",
    ),
    Rule(
        name="encoding",
        title="Bytes were decoded with the wrong codec or a truncated sequence",
        next_step=(
            "Read with an explicit encoding and errors=replace for logs, or fix the "
            "producer to emit UTF-8; never rely on the platform default."
        ),
        exception_re=r"UnicodeDecodeError|UnicodeEncodeError|UnicodeError|CharConversionException",
        message_re=r"codec|encode|decode|utf-?8|ascii|gbk",
        confidence="high",
    ),
    Rule(
        name="missing-file",
        title="A file or directory the code expects is absent",
        next_step=(
            "Resolve the path from configuration, check it at startup and print the "
            "resolved absolute path in the error message."
        ),
        exception_re=r"FileNotFoundError|NoSuchFileException|ENOENT|PathNotFound",
        message_re=r"no such file|does not exist|cannot find|ENOENT",
    ),
    Rule(
        name="permission",
        title="The process is not allowed to touch the file or socket",
        next_step=(
            "Fix ownership or mode at deploy time and assert access once during startup "
            "so the failure is not discovered mid-request."
        ),
        exception_re=r"PermissionError|AccessDeniedException|EACCES|EPERM",
        message_re=r"permission|access is denied|EACCES",
    ),
    Rule(
        name="constraint",
        title="A database constraint rejected the write",
        next_step=(
            "Make the write idempotent (upsert or ON CONFLICT) or validate uniqueness "
            "before the insert so retries cannot duplicate rows."
        ),
        exception_re=r"IntegrityError|ConstraintViolationException|UniqueViolation",
        message_re=r"unique|constraint|duplicate key",
    ),
    Rule(
        name="index-range",
        title="An index ran past the end of a sequence",
        next_step=(
            "Check the length before indexing and prefer iteration; if the list is "
            "shared across threads, snapshot it before the loop."
        ),
        exception_re=r"IndexError|ArrayIndexOutOfBoundsException",
        message_re=r"index|range|out of bounds",
    ),
)

RULE_ORDER = [rule.name for rule in RULES]


def diagnose(crash: Crash) -> list[Diagnosis]:
    """Return the root-cause hints that match, most specific first."""
    found: list[Diagnosis] = []
    for rule in RULES:
        if rule.matches(crash):
            found.append(
                Diagnosis(
                    rule=rule.name,
                    title=rule.title,
                    next_step=rule.next_step,
                    confidence=rule.confidence,
                )
            )
    found.sort(key=lambda diag: (diag.confidence != "high", RULE_ORDER.index(diag.rule)))
    return found[:MAX_STEPS]


def primary(crash: Crash) -> Diagnosis | None:
    hints = diagnose(crash)
    return hints[0] if hints else None


def catalogue() -> list[dict[str, str]]:
    """Public rule table, used by the README and the --rules flag."""
    return [
        {"rule": rule.name, "exception": rule.exception_re, "message": rule.message_re}
        for rule in RULES
    ]
