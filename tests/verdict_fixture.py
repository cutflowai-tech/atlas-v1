"""The spec §9 fixture (``fixtures/verdict/september-2026.json``, written by ``tests/make_verdict_fixture.py``) run through the engine."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from atlas_commander.verdict.engine import build_verdicts

PATH = Path(__file__).resolve().parents[1] / "fixtures" / "verdict" / "september-2026.json"


@lru_cache(maxsize=1)
def fixture() -> dict[str, Any]:
    return json.loads(PATH.read_text(encoding="utf-8"))


def verdicts() -> dict[str, Any]:
    data = fixture()
    return build_verdicts(data["dashboard"], data["intelligence"], data["dashboard"]["generated_at"])


def editor(document: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [e for e in document["editors"] if e["display_name"] == name]
    if not matches:
        raise AssertionError(f"no verdict for {name}")
    return matches[0]
