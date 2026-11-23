"""Clustering, fingerprinting and ranking tests."""

from __future__ import annotations

import datetime

from crashlens.cluster import cluster_crashes, rank, summary
from crashlens.fingerprint import (
    fingerprint,
    fingerprint_label,
    fingerprint_parts,
    normalise_function,
    normalise_message,
    normalise_type,
)
from crashlens.models import Crash, Frame, Segment

BASE = (
    "2025-01-01T10:00:00 ERROR boom\n"
    "Traceback (most recent call last):\n"
    '  File "/srv/app/{module}.py", line {line}, in run\n'
    "    do_work()\n"
    "{exc}: {msg}\n"
)


def make_crash(
    module: str = "pipeline.py",
    line: int = 31,
    exc: str = "KeyError",
    msg: str = "'items'",
    when: datetime.datetime | None = None,
) -> Crash:
    text = BASE.format(module=module, line=line, exc=exc, msg=msg)
    return Crash(
        language="python",
        segments=[
            Segment(
                exception_type=exc,
                message=msg,
                frames=(Frame(function="run", file="/srv/app/" + module, line=line),),
            )
        ],
        raw=text,
        timestamp=when or datetime.datetime(2025, 1, 1, 10, 0, 0),
    )


def test_same_shape_different_line_numbers_shares_fingerprint() -> None:
    assert fingerprint(make_crash(line=31)) == fingerprint(make_crash(line=97))


def test_different_module_splits_fingerprints() -> None:
    assert fingerprint(make_crash(module="pipeline.py")) != fingerprint(
        make_crash(module="billing.py")
    )


def test_different_exception_splits_fingerprints() -> None:
    assert fingerprint(make_crash(exc="KeyError")) != fingerprint(make_crash(exc="IndexError"))


def test_fingerprint_is_twelve_hex_characters() -> None:
    value = fingerprint(make_crash())
    assert len(value) == 12
    assert all(char in "0123456789abcdef" for char in value)


def test_fingerprint_is_stable_across_processes() -> None:
    # A hard coded expectation: changing normalisation on purpose must be a
    # deliberate change, never an accident.
    assert fingerprint(make_crash()) == "cdb9ef95eeef"


def test_fingerprint_parts_are_readable() -> None:
    parts = fingerprint_parts(make_crash())
    assert parts[0] == "python"
    assert "KeyError" in parts[1]
    assert "run@" in parts[1]
    assert parts[1].endswith("pipeline.py]")


def test_normalise_function_collapses_counters_and_addresses() -> None:
    assert normalise_function("lambda$main$12") == "lambda"
    assert normalise_function("handle0x7f3c") == "handle0xADDR"
    assert normalise_function("task_42") == "task_#"
    assert normalise_function("") == "<unknown>"


def test_normalise_type_drops_the_package() -> None:
    assert normalise_type("java.lang.NullPointerException") == "NullPointerException"
    assert normalise_type("ValueError") == "ValueError"


def test_normalise_message_removes_values_but_keeps_shape() -> None:
    first = normalise_message("failed to open /tmp/a1 for request 42")
    second = normalise_message("failed to open /tmp/b9 for request 77")
    assert first == second
    assert "open" in first


def test_normalise_message_quoted_values_are_redacted() -> None:
    assert normalise_message("KeyError: 'items'") == "KeyError: <value>"


def test_fingerprint_label_mentions_site_file() -> None:
    label = fingerprint_label(make_crash())
    assert label.startswith("KeyError at ")
    assert label.endswith("pipeline.py")


def test_cluster_groups_repeated_crashes() -> None:
    crashes = [make_crash(), make_crash(line=44), make_crash(module="other.py")]
    clusters = cluster_crashes(crashes)
    assert len(clusters) == 2
    assert clusters[0].count == 2
    assert clusters[0].sample is not None


def test_cluster_first_and_last_seen() -> None:
    early = datetime.datetime(2025, 1, 1, 9, 0, 0)
    late = datetime.datetime(2025, 1, 1, 12, 0, 0)
    cluster = cluster_crashes([make_crash(when=late), make_crash(when=early)])[0]
    assert cluster.first_seen == early
    assert cluster.last_seen == late


def test_rank_prefers_frequent_then_recent() -> None:
    old = make_crash(when=datetime.datetime(2025, 1, 1, 0, 0, 0))
    recent = make_crash(module="fresh.py", when=datetime.datetime(2025, 1, 2, 0, 0, 0))
    clusters = cluster_crashes([old, old, old, recent])
    ranked = rank(clusters)
    assert ranked[0].count == 3
    assert ranked[0].key == fingerprint(old)


def test_rank_is_deterministic_for_equal_counts() -> None:
    crashes = [make_crash(module="a.py"), make_crash(module="b.py")]
    first = [cluster.key for cluster in rank(cluster_crashes(crashes))]
    second = [cluster.key for cluster in rank(cluster_crashes(list(reversed(crashes))))]
    assert first == second


def test_cluster_without_timestamps_still_ranks() -> None:
    crash = make_crash()
    crash.timestamp = None
    clusters = rank(cluster_crashes([crash]))
    assert clusters[0].count == 1


def test_summary_counts_languages_and_window() -> None:
    java = make_crash()
    java.language = "java"
    data = summary([make_crash(), java])
    assert data["crashes"] == 2
    assert data["languages"] == {"java": 1, "python": 1}
    assert data["first_seen"] is not None


def test_summary_of_nothing_is_zeroed() -> None:
    data = summary([])
    assert data["crashes"] == 0
    assert data["languages"] == {}
    assert data["first_seen"] is None


def test_cluster_languages_and_sources() -> None:
    crash = make_crash()
    crash.language = "java"
    cluster = cluster_crashes([crash])[0]
    assert cluster.languages == ["java"]


def test_signature_chain_lists_root_cause_first() -> None:
    crash = make_crash()
    crash.segments.append(
        Segment(
            exception_type="RuntimeError",
            message="wrapped",
            frames=(Frame(function="run", file="/srv/app/pipeline.py", line=32),),
            relation="cause",
        )
    )
    cluster = cluster_crashes([crash])[0]
    # signature_chain is root-cause-first: the cause (KeyError) leads.
    assert cluster.signature_chain() == ["KeyError", "RuntimeError"]
