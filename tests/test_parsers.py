"""Parser tests: one test per language plus the edge cases that broke real logs."""

from __future__ import annotations

import pathlib

import pytest

from crashlens.models import Crash
from crashlens.parsers import FORMATS, parse_file, parse_paths, parse_text, strip_ansi

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"

PY_CHAIN = """2025-01-01 10:00:00,000 ERROR boom
Traceback (most recent call last):
  File "/app/a.py", line 3, in outer
    inner()
  File "/app/b.py", line 7, in inner
    raise KeyError("items")
KeyError: 'items'

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/app/a.py", line 4, in outer
    raise RuntimeError("wrapped") from exc
RuntimeError: wrapped
"""


def test_python_chain_is_primary_first() -> None:
    crashes = parse_text(PY_CHAIN)
    assert len(crashes) == 1
    crash = crashes[0]
    assert crash.language == "python"
    assert [segment.exception_type for segment in crash.segments] == ["RuntimeError", "KeyError"]
    assert crash.segments[1].relation == "cause"
    assert crash.primary.message == "wrapped"


def test_python_frames_are_outermost_first() -> None:
    crash = parse_text(PY_CHAIN)[0]
    assert [frame.function for frame in crash.frames] == ["outer"]
    assert crash.site_frame is not None
    assert crash.site_frame.line == 4


def test_python_timestamp_is_carried_into_the_traceback() -> None:
    crash = parse_text(PY_CHAIN)[0]
    assert crash.timestamp is not None
    assert crash.timestamp.year == 2025
    assert crash.timestamp.hour == 10


def test_parse_returns_no_crash_for_plain_noise() -> None:
    assert parse_text("INFO started\nINFO ready\n") == []


def test_empty_input_is_empty_output() -> None:
    assert parse_text("") == []


def test_ansi_colour_codes_are_stripped() -> None:
    esc = chr(27)
    coloured = (
        esc + "[31mTraceback (most recent call last):" + esc + "[0m\n"
        '  File "/a.py", line 1, in f\n'
        + esc + "[1mValueError" + esc + "[0m: bad\n"
    )
    crashes = parse_text(coloured)
    assert len(crashes) == 1
    assert crashes[0].exception_type == "ValueError"
    assert esc not in crashes[0].raw


def test_strip_ansi_keeps_text() -> None:
    esc = chr(27)
    assert strip_ansi(esc + "[32mok" + esc + "[0m") == "ok"


JAVA = """2025-01-01 10:00:00 ERROR handler failed
java.lang.NullPointerException: sku missing
\tat com.acme.OrderService.firstSku(OrderService.java:8)
\tat com.acme.Controller.handle(Controller.java:41)
\tat org.springframework.Framework.service(Framework.java:897)
\t... 24 more
Caused by: java.lang.IllegalStateException: no sku
\tat com.acme.Controller.parse(Controller.java:55)
\t... 31 more
"""


def test_java_chain_keeps_primary_then_cause() -> None:
    crash = parse_text(JAVA)[0]
    assert crash.language == "java"
    # segments are primary-first, chain is root-cause-first
    assert [segment.exception_type for segment in crash.segments] == [
        "java.lang.NullPointerException",
        "java.lang.IllegalStateException",
    ]
    assert crash.chain[1].exception_type == "java.lang.NullPointerException"
    assert crash.segments[1].relation == "cause"


def test_java_frames_are_outermost_first_and_skip_more() -> None:
    crash = parse_text(JAVA)[0]
    assert crash.frames[-1].function == "com.acme.OrderService.firstSku"
    assert all("more" not in frame.function for frame in crash.frames)


def test_java_frame_without_line_number_parses() -> None:
    text = (
        "java.lang.RuntimeException: native\n"
        "\tat com.acme.Native.call(Native Method)\n"
    )
    crash = parse_text(text)[0]
    assert crash.frames[-1].file == "Native Method"
    assert crash.frames[-1].line is None


NODE = """TypeError: Cannot read properties of undefined (reading 'sku')
    at Array.map (<anonymous>)
    at handleCheckout (/srv/acme/handlers/checkout.js:8:31)
    at processTicksAndRejections (node:internal/process/task_queues:95:5)
"""


def test_node_frames_include_columns_and_anonymous_calls() -> None:
    crash = parse_text(NODE)[0]
    assert crash.language == "node"
    # Node prints innermost first; frames are normalised to outermost first.
    assert crash.frames[0].function == "processTicksAndRejections"
    assert crash.frames[0].file == "node:internal/process/task_queues"
    assert crash.frames[-1].function == "Array.map"
    assert crash.site_frame is not None
    assert crash.site_frame.file == "/srv/acme/handlers/checkout.js"
    assert crash.site_frame.column == 31


def test_node_uncaught_prefix_is_accepted() -> None:
    text = "Uncaught RangeError: Maximum call stack size exceeded\n    at f (/app/x.js:1:1)\n"
    crash = parse_text(text)[0]
    assert crash.exception_type == "RangeError"
    assert crash.message.startswith("Maximum call stack")


GO = """panic: runtime error: invalid memory address or nil pointer dereference
[signal SIGSEGV: segmentation violation code=0x1 addr=0x18 pc=0x7f3c11]

goroutine 42 [running]:
acme/internal/queue.(*Worker).Run(0xc0000a4000)
\t/srv/acme/internal/queue/worker.go:27 +0x14a
acme/internal/queue.(*Supervisor).loop(0xc0000a8000)
\t/srv/acme/internal/queue/supervisor.go:54 +0x9d
created by acme/internal/queue.Start
\t/srv/acme/internal/queue/queue.go:19 +0x7c
"""


def test_go_panic_frames_and_creation_site() -> None:
    crash = parse_text(GO)[0]
    assert crash.language == "go"
    assert crash.exception_type == "panic"
    assert "nil pointer" in crash.message
    assert crash.frames[0].file.endswith("queue.go")
    assert crash.site_frame is not None
    assert crash.site_frame.file.endswith("worker.go")
    assert crash.site_frame.line == 27


RUST = """thread 'main' panicked at 'called Option::unwrap() on a None value', src/parser.rs:44:13
note: run with RUST_BACKTRACE=1 environment variable to display a backtrace
"""


def test_rust_panic_uses_the_reported_location() -> None:
    crash = parse_text(RUST)[0]
    assert crash.language == "rust"
    assert crash.exception_type == "panic"
    assert "Option::unwrap" in crash.message
    assert crash.frames[0].file == "src/parser.rs"
    assert crash.frames[0].line == 44
    assert crash.frames[0].column == 13


RUST_BACKTRACE = """thread 'main' panicked at src/lib.rs:12:9:
attempt to divide by zero
stack backtrace:
   0: rust_begin_unwind
             at /rustc/abc/library/std/src/panicking.rs:597:5
   1: core::panicking::panic_fmt
             at /rustc/abc/library/core/src/panicking.rs:72:14
   2: acme::divide
             at ./src/lib.rs:12:9
"""


def test_rust_backtrace_is_outermost_first() -> None:
    crash = parse_text(RUST_BACKTRACE)[0]
    assert crash.frames[-1].function == "acme::divide"
    assert crash.frames[-1].line == 12


def test_all_five_languages_parse_from_bundled_examples() -> None:
    crashes = parse_paths([str(EXAMPLES)])
    languages = {crash.language for crash in crashes}
    assert languages == set(FORMATS)


def test_example_file_roundtrip() -> None:
    crashes = parse_file(EXAMPLES / "python_error.log")
    assert len(crashes) == 2
    assert crashes[0].source.endswith("python_error.log")


def test_directory_parse_is_sorted_and_deterministic() -> None:
    first = [crash.source for crash in parse_paths([str(EXAMPLES)])]
    second = [crash.source for crash in parse_paths([str(EXAMPLES)])]
    assert first == second


def test_multi_crash_log_counts_every_record() -> None:
    text = PY_CHAIN + "\n" + NODE + "\n" + GO
    crashes = parse_text(text)
    assert len(crashes) == 3
    assert {crash.language for crash in crashes} == {"python", "node", "go"}


def test_unicode_message_is_preserved() -> None:
    cjk = chr(0x4E2D) + chr(0x6587)
    emoji = chr(0x1F4A5)
    text = (
        "Traceback (most recent call last):\n"
        '  File "/app/' + cjk + '.py", line 2, in read\n'
        "    open(path)\n"
        "UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 0: "
        "invalid start byte " + emoji + "\n"
    )
    crash = parse_text(text)[0]
    assert cjk in (crash.frames[0].file or "")
    assert emoji in crash.message


def test_large_log_parses_in_linear_time() -> None:
    block = PY_CHAIN.split("2025-01-01 10:00:00,000 ERROR boom")[1]
    text = "2025-01-01 10:00:00,000 ERROR boom" + block * 300
    crashes = parse_text(text)
    assert len(crashes) == 300


def test_parse_file_missing_raises_oserror(tmp_path: pathlib.Path) -> None:
    with pytest.raises(OSError):
        parse_file(tmp_path / "missing.log")


def test_crash_str_is_human_readable() -> None:
    crash: Crash = parse_text(NODE)[0]
    assert "TypeError" in str(crash)
