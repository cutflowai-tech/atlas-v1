"""Credential-pattern scan for deployment artifacts, docs and captured outputs (Phase 20-B).

    python deploy/production/reasoning_ops/secret_scan.py [PATH ...]      default: the tracked deployment/ops surface

Reports **only** ``path:line pattern-name`` and a pass/fail summary — never the matched text — so its own output can be pasted into a
review. Exit 0 = no finding, 1 = findings, 2 = a path could not be read.

Placeholders are allowed by design: ``REPLACE_WITH_…``, ``<...>`` and ``example.com`` hosts, ``/run/secrets/...`` and
``/etc/waset-atlas/secrets/...`` paths, and ``*_FILE=`` references. Anything that looks like a live value is a finding.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SURFACE = ("deploy", "docs", "config", "contracts", ".github", "Makefile", "README.md", "requirements.txt", "requirements-reasoning.txt")

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openrouter_key", re.compile(r"sk-or-(?:v\d-)?[A-Za-z0-9]{16,}")),
    ("anthropic_or_openai_key", re.compile(r"\bsk-(?!or-)(?:ant-|proj-)?[A-Za-z0-9_-]{24,}")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+(?!<|\$|\{|TOKEN\b|REDACTED)[A-Za-z0-9._~+/=-]{16,}")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("database_url_with_password", re.compile(r"postgres(?:ql)?(?:\+[a-z0-9]+)?://[^\s:/@'\"]+:(?!\*\*\*|<|\$\{|REPLACE)[^\s@'\"]+@")),
    ("assigned_secret", re.compile(r"(?m)^\s*(?:export\s+)?(?:[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD))\s*[=:]\s*(?!\s*$|<|\$|\"?REPLACE|/)[^\s#]{8,}")),
    ("libpq_keyword_password", re.compile(r"(?i)\b(?:host|hostaddr|dbname|user|port)=\S+[^\n]*?\bpassword=(?!\*\*\*|<|\$)['\"]?[^\s'\"]{4,}")),
    ("json_secret", re.compile(r"(?i)\"[a-z0-9_]*(?:api_key|apikey|token|secret|password)\"\s*:\s*\"(?!\*\*\*|<|REPLACE|\$|/)[^\"\s]{8,}\"")),
    ("monday_token_jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
)
# Known, documented CI-only / test-only values in the default surface (never credentials of any real system).
ALLOWED_LITERALS = ("atlas-ci-only",)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    pattern: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line} {self.pattern}"


def tracked(paths: Sequence[str]) -> list[Path]:
    output = subprocess.run(["git", "ls-files", "-z", "--", *paths], cwd=ROOT, check=True, capture_output=True).stdout
    return [ROOT / name for name in output.decode().split("\0") if name]


def scan_text(text: str, path: str) -> list[Finding]:
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        for literal in ALLOWED_LITERALS:                     # remove the documented literal itself; the rest of the line is still scanned
            line = line.replace(literal, "")
        for name, pattern in PATTERNS:
            if pattern.search(line):
                findings.append(Finding(path, number, name))
    return findings


def scan(paths: Iterable[Path]) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    unreadable: list[str] = []
    for path in paths:
        if path.is_dir():
            inner, bad = scan(sorted(p for p in path.rglob("*") if p.is_file()))
            findings += inner
            unreadable += bad
            continue
        try:
            data = path.read_bytes()
        except OSError:
            unreadable.append(_display(path))
            continue
        if b"\0" in data[:4096]:
            continue                        # binary (e.g. a pg_dump artifact): scanned by its producer's manifest, not here
        findings += scan_text(data.decode("utf-8", errors="replace"), _display(path))
    return findings, unreadable


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return path.name


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    paths = [Path(arg) for arg in args] if args else tracked(DEFAULT_SURFACE)
    findings, unreadable = scan(paths)
    print(json.dumps({"result": "fail" if findings or unreadable else "pass", "files": len(paths), "findings": [str(f) for f in findings],
                      "unreadable": unreadable}, sort_keys=True))
    return 2 if unreadable else 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
