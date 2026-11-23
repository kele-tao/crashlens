"""Heuristics, repository matching and blame-since correlation tests."""

from __future__ import annotations

import pathlib

from crashlens import heuristics
from crashlens.engine import UserError, analyse, annotate_first, blame_since
from crashlens.parsers import parse_text
from crashlens.repo import Repo, normalise_path

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
DEMO = EXAMPLES / "demo_repo"


def crash_from(exception: str, message: str, frames):
    text = (
        'Traceback (most recent call last):\n'
        '  File "/srv/app/run.py", line 1, in main\n'
        "    run()\n"
        + exception
        + ": "
        + message
        + "\n"
    )
    crash = parse_text(text)[0]
    if frames:
        crash.segments[0] = crash.segments[0].__class__(
            exception_type=crash.segments[0].exception_type,
            message=crash.segments[0].message,
            frames=tuple(frames),
        )
    return crash


def test_rule_catalogue_is_public_and_non_empty() -> None:
    rules = heuristics.catalogue()
    assert len(rules) >= 10
    assert all("rule" in rule and "exception" in rule for rule in rules)


def test_none_type_error_maps_to_optional_guard() -> None:
    crash = parse_text(
        "TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'\n"
        "    at main (/srv/app/x.js:1:1)\n"
    )[0]
    hints = heuristics.diagnose(crash)
    assert hints[0].rule == "none-optional"
    assert hints[0].confidence == "high"
    assert "None" in hints[0].title or "None" in hints[0].next_step


def test_connection_reset_maps_to_retry_advice() -> None:
    crash = parse_text(
        "ConnectionResetError: [Errno 104] Connection reset by peer\n"
        "Traceback (most recent call last):\n"
        '  File "/srv/app/net.py", line 8, in fetch\n'
        "    sock.read()\n"
        "ConnectionResetError: [Errno 104] Connection reset by peer\n"
    )[0]
    rules = [hint.rule for hint in heuristics.diagnose(crash)]
    assert "transient-network" in rules


def test_encoding_error_maps_to_explicit_codec() -> None:
    crash = parse_text(
        "Traceback (most recent call last):\n"
        '  File "/srv/app/io.py", line 3, in load\n'
        "    path.read_text()\n"
        "UnicodeDecodeError: 'ascii' codec can't decode byte 0xe4 in position 0\n"
    )[0]
    assert heuristics.diagnose(crash)[0].rule == "encoding"


def test_memory_and_recursion_rules_are_distinct() -> None:
    memory = parse_text(
        "Traceback (most recent call last):\n"
        '  File "/srv/app/x.py", line 1, in f\n'
        "    big()\n"
        "MemoryError: unable to allocate array\n"
    )[0]
    recursion = parse_text(
        "Traceback (most recent call last):\n"
        '  File "/srv/app/x.py", line 1, in f\n'
        "    f()\n"
        "RecursionError: maximum recursion depth exceeded\n"
    )[0]
    assert heuristics.primary(memory).rule == "memory"
    assert heuristics.primary(recursion).rule == "recursion"


def test_unknown_exception_has_no_hint() -> None:
    crash = parse_text(
        "Traceback (most recent call last):\n"
        '  File "/srv/app/x.py", line 1, in f\n'
        "    raise CustomError\n"
        "CustomError: something odd\n"
    )[0]
    assert heuristics.diagnose(crash) == []


def test_diagnosis_serialises() -> None:
    crash = parse_text(
        "Traceback (most recent call last):\n"
        '  File "/srv/app/x.py", line 1, in f\n'
        "    open(p)\n"
        "FileNotFoundError: [Errno 2] No such file or directory: '/tmp/x'\n"
    )[0]
    hint = heuristics.primary(crash)
    assert hint is not None
    payload = hint.as_dict()
    assert payload["rule"] == "missing-file"
    assert payload["next_step"]


def test_repo_locate_resolves_absolute_and_relative_paths() -> None:
    repo = Repo(DEMO)
    assert repo.locate("pipeline.py") is not None
    absolute = str((DEMO / "pipeline.py").resolve())
    assert repo.locate(absolute) is not None


def test_repo_locate_ignores_library_paths() -> None:
    repo = Repo(DEMO)
    assert repo.locate("node:internal/process/task_queues") is None
    assert repo.locate("/usr/lib/python3/site-packages/requests/api.py") is None


def test_repo_is_owned_distinguishes_project_and_vendor() -> None:
    crash = parse_text(
        'Traceback (most recent call last):\n'
        '  File "' + str(DEMO / "pipeline.py") + '", line 20, in pick_sku\n'
        "    items = document[\"items\"]\n"
        "KeyError: 'items'\n"
    )[0]
    repo = Repo(DEMO)
    assert repo.is_owned(crash.frames[-1])
    assert not repo.is_owned(
        crash.frames[-1].__class__(function="get", file="site-packages/requests/api.py", line=1)
    )


def test_repo_missing_directory_raises() -> None:
    import pytest

    from crashlens.repo import RepoError

    with pytest.raises(RepoError):
        Repo("definitely/not/here")


def test_normalise_path_strips_absolute_prefixes() -> None:
    assert normalise_path("/srv/app/pipeline.py") == "srv/app/pipeline.py"
    assert normalise_path("C:/build/tmp1234/pipeline.py").endswith("pipeline.py")
    assert normalise_path("site-packages/requests/api.py") == "site-packages/requests/api.py"


def test_analyse_groups_bundled_examples() -> None:
    analysis = analyse([str(EXAMPLES)], repo_path=str(DEMO))
    assert analysis.repo is not None
    assert len(analysis.clusters) >= 5
    assert sum(cluster.count for cluster in analysis.clusters) == len(analysis.crashes)


def test_analyse_without_repo_uses_crash_site() -> None:
    analysis = analyse([str(EXAMPLES / "node_async_error.log")])
    assert analysis.repo is None
    cluster = analysis.clusters[0]
    assert cluster.count == 2


def test_analyse_missing_path_is_a_user_error() -> None:
    import pytest

    with pytest.raises(UserError):
        analyse(["no-such-file.log"])


def test_annotate_first_finds_the_buggy_line() -> None:
    annotation = annotate_first([str(EXAMPLES / "python_error.log")], str(DEMO))
    assert annotation.resolved
    assert annotation.relative_path == "pipeline.py"
    assert annotation.lines
    target = [line for line in annotation.lines if line.is_target]
    assert len(target) == 1
    assert "items" in target[0].text
    assert annotation.blame is not None
    assert annotation.blame.author == "Priya Nair"
    assert annotation.marker == "KeyError"


def test_annotate_without_blame_still_resolves() -> None:
    annotation = annotate_first([str(EXAMPLES / "python_error.log")], str(DEMO), blame=False)
    assert annotation.blame is None
    assert annotation.resolved


def test_annotate_unresolved_when_repo_does_not_contain_file(tmp_path: pathlib.Path) -> None:
    (tmp_path / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
    annotation = annotate_first([str(EXAMPLES / "go_panic.log")], str(tmp_path))
    assert not annotation.resolved
    assert annotation.lines == []


def test_blame_since_correlates_the_regression() -> None:
    correlation = blame_since([str(EXAMPLES / "python_error.log")], str(DEMO), "HEAD~1")
    assert correlation.matched
    assert correlation.changed[0].path == "pipeline.py"
    assert correlation.changed[0].commits[0].summary.startswith("refactor")


def test_blame_since_rejects_unknown_revision() -> None:
    import pytest

    with pytest.raises(UserError):
        blame_since([str(EXAMPLES / "go_panic.log")], str(DEMO), "does-not-exist")


def test_blame_since_requires_a_git_repository(tmp_path: pathlib.Path) -> None:
    import pytest

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(UserError):
        blame_since([str(EXAMPLES / "go_panic.log")], str(tmp_path), "HEAD")
