"""Deterministic crash clustering, recency ranking and per-cluster analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from . import heuristics
from .fingerprint import actionable_frame, fingerprint, fingerprint_label
from .gitinfo import Blame, blame_line
from .models import Crash, Frame
from .repo import Repo

RECENCY_WEIGHT = 1.0


@dataclass
class Cluster:
    """A set of crashes that share a fingerprint."""

    key: str
    crashes: list[Crash] = field(default_factory=list)
    sample: Crash | None = None

    @property
    def count(self) -> int:
        return len(self.crashes)

    @property
    def first_seen(self) -> datetime | None:
        stamps = [c.timestamp for c in self.crashes if c.timestamp is not None]
        return min(stamps) if stamps else None

    @property
    def last_seen(self) -> datetime | None:
        stamps = [c.timestamp for c in self.crashes if c.timestamp is not None]
        return max(stamps) if stamps else None

    @property
    def languages(self) -> list[str]:
        return sorted({crash.language for crash in self.crashes})

    @property
    def sources(self) -> list[str]:
        return sorted({crash.source for crash in self.crashes if crash.source})

    @property
    def label(self) -> str:
        return fingerprint_label(self.sample) if self.sample else "<empty>"

    def actionable(self, repo: Repo | None) -> tuple[Frame | None, Frame | None]:
        """(actionable frame, crash site frame) for the cluster sample."""
        crash = self.sample
        if crash is None:
            return None, None
        return actionable_frame(crash, repo), crash.site_frame

    def diagnoses(self) -> list[heuristics.Diagnosis]:
        if self.sample is None:
            return []
        return heuristics.diagnose(self.sample)

    def signature_chain(self) -> list[str]:
        if self.sample is None:
            return []
        return list(reversed(self.sample.chain_types))


def cluster_crashes(crashes: list[Crash]) -> list[Cluster]:
    """Group crashes by fingerprint, preserving first-appearance order."""
    buckets: dict[str, Cluster] = {}
    for crash in crashes:
        key = fingerprint(crash)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = Cluster(key=key, sample=crash)
            buckets[key] = bucket
        bucket.crashes.append(crash)
    return list(buckets.values())


def recency_score(cluster: Cluster, window: tuple[datetime, datetime] | None) -> float:
    """Linear recency in [0, 1] over the parsed time window (0.5 when unknown)."""
    if window is None or cluster.last_seen is None:
        return 0.5
    start, end = window
    span = (end - start).total_seconds()
    if span <= 0:
        return 1.0
    return max(0.0, min(1.0, (cluster.last_seen - start).total_seconds() / span))


def rank(clusters: list[Cluster]) -> list[Cluster]:
    """Sort by frequency multiplied by recency, then by key for determinism.

    The score is intentionally simple and documented in the README:
        score = count * (1 + recency)
    where recency is the cluster's last-seen position inside the log's time
    window, in [0, 1].  A crash seen 70 times at the start of the window
    scores 70; one seen 40 times at the very end scores 80 and wins, which is
    the behaviour an on-call engineer wants when ranking a log directory.
    """
    stamps = [c.timestamp for cluster in clusters for c in cluster.crashes if c.timestamp]
    window = (min(stamps), max(stamps)) if stamps else None
    return sorted(
        clusters,
        key=lambda cluster: (
            -(cluster.count * (1 + RECENCY_WEIGHT * recency_score(cluster, window))),
            cluster.key,
        ),
    )


def summary(crashes: list[Crash]) -> dict[str, object]:
    """Small aggregate used by every renderer."""
    by_language: dict[str, int] = {}
    for crash in crashes:
        by_language[crash.language] = by_language.get(crash.language, 0) + 1
    stamps = [crash.timestamp for crash in crashes if crash.timestamp]
    return {
        "crashes": len(crashes),
        "languages": dict(sorted(by_language.items())),
        "first_seen": min(stamps).isoformat() if stamps else None,
        "last_seen": max(stamps).isoformat() if stamps else None,
    }


@dataclass
class ClusterBlame:
    """Blame attribution for the actionable frame of a cluster."""

    cluster_key: str
    path: str
    line: int
    blame: Blame


def blame_clusters(clusters: list[Cluster], repo: Repo) -> list[ClusterBlame]:
    """Attach git blame to every cluster that resolves inside *repo*.

    Used by the HTML report and the JSON output so a reader can see which
    commit introduced the line that is crashing, without a second command.
    """
    found: list[ClusterBlame] = []
    for cluster in clusters:
        frame = actionable_frame(cluster.sample, repo) if cluster.sample else None
        if frame is None or not frame.file or frame.line is None:
            continue
        path = repo.locate(frame.file)
        if path is None:
            continue
        relative = repo.relative(path)
        blame = blame_line(repo.root, relative, frame.line)
        if blame is None:
            continue
        found.append(
            ClusterBlame(cluster_key=cluster.key, path=relative, line=frame.line, blame=blame)
        )
    return found
