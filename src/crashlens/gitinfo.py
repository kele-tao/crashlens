"""Thin, defensive wrapper around the git CLI used by annotate / blame-since."""

from __future__ import annotations

import pathlib
import subprocess
from dataclasses import dataclass
from datetime import date, datetime


class GitError(RuntimeError):
    """Raised when git is missing, the path is not a repository or a command fails."""


@dataclass(frozen=True)
class Blame:
    """Attribution for one source line."""

    commit: str
    author: str
    date: datetime | None
    summary: str

    @property
    def short_commit(self) -> str:
        return self.commit[:7]

    @property
    def day(self) -> str:
        return self.date.strftime("%Y-%m-%d") if self.date else "unknown date"

    def describe(self) -> str:
        """One line attribution: 'abc1234 by Alice on 2026-01-04 - fix parser'."""
        return (
            self.short_commit
            + " by "
            + (self.author or "unknown")
            + " on "
            + self.day
            + ((" - " + self.summary) if self.summary else "")
        )


@dataclass(frozen=True)
class Commit:
    """One commit in a range."""

    sha: str
    author: str
    date: datetime | None
    summary: str

    @property
    def short_sha(self) -> str:
        return self.sha[:7]


def _run(repo: str | pathlib.Path, args: list[str], timeout: float = 20.0) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "PATH": _path()},
        )
    except FileNotFoundError as exc:
        raise GitError(
            "git is not installed or not on PATH; crashlens annotate needs git for blame "
            "(pass --no-blame to skip)"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError("git " + " ".join(args) + " timed out after " + str(timeout) + "s") from exc
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout).strip() or "exit code " + str(proc.returncode)
        raise GitError("git " + " ".join(args) + " failed: " + message)
    return proc.stdout


def _path() -> str:
    import os

    return os.environ.get("PATH", "")


def is_repo(repo: str | pathlib.Path) -> bool:
    """True when *repo* is inside a git working tree."""
    try:
        out = _run(repo, ["rev-parse", "--is-inside-work-tree"], timeout=10.0)
    except GitError:
        return False
    return out.strip() == "true"


def head(repo: str | pathlib.Path) -> str:
    return _run(repo, ["rev-parse", "HEAD"], timeout=10.0).strip()


def parse_git_date(text: str) -> datetime | None:
    """Parse the timestamp formats git prints (ISO with offset, or unix epoch)."""
    token = text.strip()
    if not token:
        return None
    if token.isdigit():
        try:
            return datetime.fromtimestamp(int(token))
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(token)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(token, fmt)
        except ValueError:
            continue
    try:
        return datetime.combine(date.fromisoformat(token[:10]), datetime.min.time())
    except ValueError:
        return None


def blame_line(repo: str | pathlib.Path, relative_path: str, line: int) -> Blame | None:
    """Return blame attribution for a single line, or None when unavailable.

    Uses --porcelain so the parser only depends on a stable, documented format.
    Lines that are not committed yet come back as 0000000 with the *Not
    Committed Yet* author; callers get that verbatim because it is the truth.
    """
    if line <= 0:
        return None
    try:
        out = _run(repo, ["blame", "--porcelain", "-L", str(line) + "," + str(line), "--", relative_path])
    except GitError:
        return None
    if not out:
        return None
    sha = ""
    author = ""
    timestamp = ""
    summary = ""
    for line_number, raw in enumerate(out.splitlines()):
        if raw.startswith("author "):
            author = raw[len("author "):].strip()
        elif raw.startswith("author-time "):
            timestamp = raw[len("author-time "):].strip()
        elif raw.startswith("summary "):
            summary = raw[len("summary "):].strip()
        elif line_number == 0:
            token = raw.split(" ")[0] if raw else ""
            if len(token) >= 8 and all(char in "0123456789abcdef" for char in token):
                sha = token
    if not sha:
        return None
    return Blame(commit=sha, author=author, date=parse_git_date(timestamp), summary=summary)


def commits_touching(
    repo: str | pathlib.Path, relative_path: str, since: str | None = None
) -> list[Commit]:
    """Commits that touched one file, newest first."""
    args = ["log", "--format=%H%x1f%an%x1f%aI%x1f%s", "-n", "20"]
    if since:
        args.append(since + "..HEAD")
    args.extend(["--", relative_path])
    try:
        out = _run(repo, args)
    except GitError:
        return []
    return _parse_log(out)


def _parse_log(out: str) -> list[Commit]:
    commits: list[Commit] = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        commits.append(
            Commit(
                sha=parts[0].strip(),
                author=parts[1].strip(),
                date=parse_git_date(parts[2]),
                summary=parts[3].strip(),
            )
        )
    return commits


def resolve(repo: str | pathlib.Path, revision: str) -> str:
    """Resolve a revision to a full sha, raising a friendly GitError."""
    try:
        out = _run(repo, ["rev-parse", "--verify", revision + "^{commit}"], timeout=10.0)
    except GitError as exc:
        raise GitError(
            "unknown revision '" + revision + "': pass a commit sha or ref that exists in "
            + str(repo)
        ) from exc
    return out.strip()


def changed_files(repo: str | pathlib.Path, since: str) -> list[str]:
    """Repository-relative paths touched between *since* and HEAD."""
    out = _run(repo, ["diff", "--name-only", since + "..HEAD"])
    files = [line.strip() for line in out.splitlines() if line.strip()]
    files.sort()
    return files


def range_commits(repo: str | pathlib.Path, since: str) -> list[Commit]:
    """Commits between *since* (exclusive) and HEAD, newest first."""
    out = _run(repo, ["log", "--format=%H%x1f%an%x1f%aI%x1f%s", since + "..HEAD"])
    return _parse_log(out)


def first_commit_after(repo: str | pathlib.Path, since: str, relative_path: str) -> Commit | None:
    """Oldest commit that touched a file inside the range since..HEAD."""
    out = _run(
        repo,
        ["log", "--format=%H%x1f%an%x1f%aI%x1f%s", "--reverse", since + "..HEAD", "--", relative_path],
    )
    commits = _parse_log(out)
    return commits[0] if commits else None
