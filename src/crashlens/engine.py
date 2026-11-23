"""High level operations used by the CLI (parse, cluster, annotate, blame-since)."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

from . import gitinfo
from .annotate import Annotation, annotate_crash
from .cluster import Cluster, cluster_crashes, rank
from .fingerprint import actionable_frame, fingerprint_label, normalise_path
from .gitinfo import GitError
from .models import Crash
from .parsers import parse_file, parse_paths
from .repo import Repo, RepoError


class UserError(Exception):
    """A problem the user can fix; the CLI prints it without a traceback."""


@dataclass
class Analysis:
    """Everything produced by reading a set of paths."""

    crashes: list[Crash] = field(default_factory=list)
    clusters: list[Cluster] = field(default_factory=list)
    repo: Repo | None = None


def open_repo(path: str | None) -> Repo | None:
    """Open a repository root, translating failures into a user facing error."""
    if not path:
        return None
    try:
        return Repo(path)
    except RepoError as exc:
        raise UserError(str(exc)) from exc


def load_crashes(paths: list[str], encoding: str = "utf-8") -> list[Crash]:
    """Parse files and directories, raising UserError for missing inputs."""
    if not paths:
        raise UserError("no input files given; pass a log file or a directory")
    missing = [path for path in paths if not pathlib.Path(path).exists()]
    if missing:
        raise UserError("input not found: " + ", ".join(missing))
    try:
        if encoding == "utf-8":
            return parse_paths(paths)
        crashes: list[Crash] = []
        for item in paths:
            target = pathlib.Path(item)
            if target.is_dir():
                for child in sorted(p for p in target.rglob("*") if p.is_file()):
                    if child.suffix.lower() in {".log", ".txt", ".out", ".err", ".trace"}:
                        crashes.extend(parse_file(child, encoding=encoding))
            else:
                crashes.extend(parse_file(target, encoding=encoding))
        return crashes
    except OSError as exc:
        raise UserError("cannot read input: " + str(exc)) from exc


def analyse(
    paths: list[str],
    repo_path: str | None = None,
    encoding: str = "utf-8",
) -> Analysis:
    """Parse *paths*, cluster the result and attach the optional repository."""
    crashes = load_crashes(paths, encoding=encoding)
    repo = open_repo(repo_path)
    return Analysis(crashes=crashes, clusters=rank(cluster_crashes(crashes)), repo=repo)


def annotate_first(
    paths: list[str],
    repo_path: str | None,
    context: int = 3,
    blame: bool = True,
    frame_choice: str = "actionable",
) -> Annotation:
    """Annotate the first crash found under *paths*.

    `frame_choice` selects which frame is annotated: the deepest project owned
    frame ("actionable") or the exception's innermost frame ("deepest").
    """
    analysis = analyse(paths, repo_path)
    if not analysis.crashes:
        raise UserError("no crash records found in " + ", ".join(paths))
    crash = analysis.crashes[0]
    frame = None
    if frame_choice == "deepest":
        frame = crash.deepest_frame
    else:
        frame = actionable_frame(crash, analysis.repo)
    return annotate_crash(crash, analysis.repo, context=context, use_blame=blame, frame=frame)


@dataclass
class ChangedFile:
    """A repository file touched since a deploy, with the crashes that hit it."""

    path: str
    commits: list[gitinfo.Commit]
    clusters: list[Cluster]


@dataclass
class DeployCorrelation:
    """Result of blame-since: crashes grouped by the changed file they hit."""

    since: str
    full_sha: str
    repo: Repo
    commits: list[gitinfo.Commit]
    changed: list[ChangedFile]
    matched: list[Cluster]
    unmatched: list[Cluster]


def blame_since(
    paths: list[str],
    repo_path: str,
    since: str,
    encoding: str = "utf-8",
) -> DeployCorrelation:
    """Correlate crashes with files and commits that changed after *since*."""
    repo = open_repo(repo_path)
    assert repo is not None
    if not repo.is_git():
        raise UserError("not a git repository: " + str(repo.root))
    try:
        full_sha = gitinfo.resolve(repo.root, since)
        commits = gitinfo.range_commits(repo.root, since)
    except GitError as exc:
        raise UserError(str(exc)) from exc
    crashes = load_crashes(paths, encoding=encoding)
    clusters = rank(cluster_crashes(crashes))
    try:
        changed_paths = gitinfo.changed_files(repo.root, since)
    except GitError as exc:
        raise UserError(str(exc)) from exc
    changed = [
        ChangedFile(
            path=path,
            commits=gitinfo.commits_touching(repo.root, path, since),
            clusters=[],
        )
        for path in changed_paths
    ]
    by_path = {entry.path: entry for entry in changed}
    matched: list[Cluster] = []
    unmatched: list[Cluster] = []
    for cluster in clusters:
        hits: set[str] = set()
        for crash in cluster.crashes:
            for frame in crash.all_frames:
                located = repo.locate(frame.file)
                if located is None:
                    continue
                relative = repo.relative(located)
                if relative in by_path:
                    hits.add(relative)
        if hits:
            for hit in sorted(hits):
                by_path[hit].clusters.append(cluster)
            matched.append(cluster)
        else:
            unmatched.append(cluster)
    return DeployCorrelation(
        since=since,
        full_sha=full_sha,
        repo=repo,
        commits=commits,
        changed=changed,
        matched=matched,
        unmatched=unmatched,
    )


def deploy_delta(correlation: DeployCorrelation) -> dict[str, object]:
    """JSON payload for blame-since."""
    return {
        "since": correlation.since,
        "resolved_sha": correlation.full_sha,
        "repo": str(correlation.repo.root),
        "commits": [
            {
                "sha": commit.sha,
                "author": commit.author,
                "date": commit.date.isoformat() if commit.date else None,
                "summary": commit.summary,
            }
            for commit in correlation.commits
        ],
        "changed_files": [
            {
                "path": entry.path,
                "commits": [
                    {"sha": commit.sha, "summary": commit.summary} for commit in entry.commits
                ],
                "clusters": [cluster.key for cluster in entry.clusters],
            }
            for entry in correlation.changed
        ],
        "matched_clusters": [cluster.key for cluster in correlation.matched],
        "unmatched_clusters": [cluster.key for cluster in correlation.unmatched],
    }


def describe_frame(cluster: Cluster, repo: Repo | None) -> str:
    """One line summary of a cluster location used by several renderers."""
    frame = actionable_frame(cluster.sample, repo) if cluster.sample else None
    if frame is None:
        return fingerprint_label(cluster.sample) if cluster.sample else "<empty>"
    return (frame.file or "<unknown>") + (":" + str(frame.line) if frame.line else "")


def normalised_location(cluster: Cluster) -> str:
    """Machine independent location label, used in tests and JSON."""
    frame = cluster.sample.deepest_frame if cluster.sample else None
    if frame is None or frame.file is None:
        return "<unknown>"
    return normalise_path(frame.file)
