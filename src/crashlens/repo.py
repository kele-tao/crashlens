"""Map traceback paths onto a checkout so frames can be judged and annotated."""

from __future__ import annotations

import pathlib
import re

from .models import Frame

VENDOR_DIRS = frozenset(
    {
        "site-packages",
        "dist-packages",
        "node_modules",
        "third_party",
        "third-party",
        "vendor",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".git",
        "target",
        "build",
        "dist",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
    }
)

SKIP_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".dylib",
        ".class",
        ".jar",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".zip",
        ".gz",
        ".whl",
        ".lock",
    }
)

MAX_INDEX_FILES = 60_000


class RepoError(Exception):
    """Raised when a repository root cannot be used."""


class Repo:
    """A checkout on disk that frames are matched against.

    The matching is deliberately permissive: production tracebacks contain
    absolute build-machine paths, container paths, bare relative paths and
    vendored paths all in the same stack.  We keep the most specific match
    (exact relative path, then suffix, then basename) and cache every lookup.
    """

    def __init__(self, root: str | pathlib.Path) -> None:
        self.root = pathlib.Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise RepoError("repository directory does not exist: " + str(root))
        self._files: list[str] | None = None
        self._locate_cache: dict[str, pathlib.Path | None] = {}
        self._owned_cache: dict[tuple[str, int | None], bool] = {}

    def files(self) -> list[str]:
        """Repository-relative POSIX paths, sorted for deterministic matching."""
        if self._files is None:
            found: list[str] = []
            for path in self.root.rglob("*"):
                if len(found) >= MAX_INDEX_FILES:
                    break
                try:
                    if not path.is_file():
                        continue
                except OSError:
                    continue
                if path.suffix.lower() in SKIP_SUFFIXES:
                    continue
                rel_parts = path.relative_to(self.root).parts
                if any(part in VENDOR_DIRS for part in rel_parts):
                    continue
                found.append("/".join(rel_parts))
            found.sort()
            self._files = found
        return self._files

    @staticmethod
    def clean(frame_path: str) -> str:
        return frame_path.replace("\\", "/").strip().lstrip("./")

    def locate(self, frame_path: str | None) -> pathlib.Path | None:
        """Resolve a frame path to a file inside the repository, if possible."""
        if not frame_path:
            return None
        if frame_path in self._locate_cache:
            return self._locate_cache[frame_path]
        resolved = self._locate(frame_path)
        self._locate_cache[frame_path] = resolved
        return resolved

    def _locate(self, frame_path: str) -> pathlib.Path | None:
        if frame_path.startswith("node:") or frame_path.startswith("<"):
            return None
        cleaned = self.clean(frame_path)
        if not cleaned:
            return None
        direct = pathlib.Path(cleaned)
        if direct.is_absolute() and direct.is_file():
            try:
                direct.resolve().relative_to(self.root)
                return direct
            except (ValueError, OSError):
                pass
        rel_clean = cleaned.lstrip("/")
        relative = self.root / rel_clean
        if relative.is_file() and not self._is_vendor(relative):
            return relative
        candidates: list[str] = []
        for rel in self.files():
            if rel == rel_clean:
                return self.root / rel
            if rel_clean.endswith("/" + rel) or rel.endswith("/" + rel_clean):
                candidates.append(rel)
        if not candidates and "/" not in rel_clean:
            for rel in self.files():
                if pathlib.PurePosixPath(rel).name == rel_clean:
                    candidates.append(rel)
        if not candidates:
            return None
        candidates.sort(key=lambda item: (len(item), item))
        return self.root / candidates[0]

    def _is_vendor(self, path: pathlib.Path) -> bool:
        try:
            parts = path.resolve().relative_to(self.root).parts
        except (ValueError, OSError):
            return False
        return any(part in VENDOR_DIRS for part in parts)

    def is_owned(self, frame: Frame) -> bool:
        """True when the frame lives in this checkout and is not vendored."""
        if frame.file is None:
            return False
        key = (frame.file, frame.line)
        if key in self._owned_cache:
            return self._owned_cache[key]
        located = self.locate(frame.file)
        owned = located is not None and not self._is_vendor(located)
        self._owned_cache[key] = owned
        return owned

    def relative(self, path: pathlib.Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except (ValueError, OSError):
            return path.as_posix()

    def read_lines(self, path: pathlib.Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

    def is_git(self) -> bool:
        return (self.root / ".git").exists()

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return "Repo(" + str(self.root) + ")"


TEMP_SEGMENT_RE = re.compile(r"^(?:tmp|temp)[0-9a-z_.-]{4,}$|^[0-9a-f]{8,}$", re.IGNORECASE)


def normalise_path(path: str) -> str:
    """Reduce a frame path to a stable, machine-independent form.

    Absolute prefixes, temp directory names, build hashes and Windows drive
    letters all change between runs of the same crash; the module path does
    not.  This is what makes clustering across hosts possible.
    """
    cleaned = path.replace("\\", "/")
    while "//" in cleaned:
        cleaned = cleaned.replace("//", "/")
    for marker in ("site-packages/", "dist-packages/", "node_modules/"):
        if marker in cleaned:
            cleaned = marker + cleaned.split(marker, 1)[1]
            break
    parts = [part for part in cleaned.split("/") if part not in {"", "."}]
    normalised: list[str] = []
    for part in parts:
        if TEMP_SEGMENT_RE.match(part):
            normalised.append("<tmp>")
        else:
            normalised.append(part)
    if len(normalised) > 4 and not normalised[0].endswith(":"):
        normalised = normalised[-4:]
    return "/".join(normalised)
