"""Find direction-sensitive values in Arabic pages that are not inside an isolating element (redesign T1.4)."""

from __future__ import annotations

import re
from html.parser import HTMLParser

ISOLATING = {"bdi", "code", "time"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
PATTERNS = {
    "id": re.compile(r"\b\d{7,}\b"),
    "iso_time": re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"),
    "date": re.compile(r"\b\d{1,2} [؀-ۿ]+ \d{4}"),
    "percent": re.compile(r"\d+(?:\.\d+)?%"),
    "latin": re.compile(r"[A-Za-z][A-Za-z0-9 _.\-]*[A-Za-z0-9]"),
}


class _Checker(HTMLParser):
    def __init__(self, kinds: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self.kinds = kinds
        self.stack: list[tuple[str, bool]] = []
        self.skip = 0
        self.problems: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "title"):
            self.skip += 1
        if tag in VOID:
            return
        isolating = tag in ISOLATING or (tag != "html" and any(name == "dir" for name, _ in attrs))
        self.stack.append((tag, isolating))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "title"):
            self.skip -= 1
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self.skip or any(isolating for _, isolating in self.stack):
            return
        for kind in self.kinds:
            for match in PATTERNS[kind].finditer(data):
                self.problems.append((kind, match.group(0), data.strip()[:120]))


def unisolated(page: str, kinds: tuple[str, ...] = tuple(PATTERNS)) -> list[tuple[str, str, str]]:
    checker = _Checker(kinds)
    checker.feed(page)
    return checker.problems
