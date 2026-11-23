"""Minimal ANSI styling: no dependency, no colour when not wanted."""

from __future__ import annotations

import os

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
CYAN = "\x1b[36m"
GREY = "\x1b[90m"


def supports_color(stream) -> bool:
    """Respect NO_COLOR, FORCE_COLOR and whether the stream is a terminal."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return bool(getattr(stream, "isatty", lambda: False)())


class Painter:
    """Apply ANSI codes only when colour is enabled."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def paint(self, text: str, *codes: str) -> str:
        if not self.enabled or not codes:
            return text
        return "".join(codes) + text + RESET

    def bold(self, text: str) -> str:
        return self.paint(text, BOLD)

    def dim(self, text: str) -> str:
        return self.paint(text, GREY)

    def red(self, text: str) -> str:
        return self.paint(text, RED)

    def green(self, text: str) -> str:
        return self.paint(text, GREEN)

    def yellow(self, text: str) -> str:
        return self.paint(text, YELLOW)

    def cyan(self, text: str) -> str:
        return self.paint(text, CYAN)

    def magenta(self, text: str) -> str:
        return self.paint(text, MAGENTA)
