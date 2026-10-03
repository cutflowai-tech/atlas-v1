"""Reasoning V3 release thresholds (Phase 19, ``REV/19`` #7): versioned, machine-readable, evaluated exactly.

The thresholds live in a JSON file next to the golden cases (``evaluation_golden/release-thresholds-v1.json``); this module loads and
validates it and compares every metric with its bound **exactly** (``fractions.Fraction``: ``0.05`` is 1/20, never a float), so a
value equal to the bound is on the passing side of ``<=`` / ``>=`` and nothing is lost to rounding.

Integrity rules (also in ``docs/REASONING-V3-EVALUATION.md``):

- a threshold set is identified by its ``version``; changing a bound or a rule is a **new version** with a written rationale, never an
  edit of an existing one, and never a change made because the current implementation fails it;
- a release threshold fails on no data (``on_no_data = fail``): a property the suite did not measure is not shown;
- every metric the harness defines must have exactly one threshold, so no metric can silently stop gating a release.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

from atlas_reasoning.evaluation_metrics import METRIC_NAMES
from atlas_reasoning.evaluation_types import (
    THRESHOLD_SCHEMA_VERSION,
    Comparator,
    EvaluationMetric,
    FixtureError,
    NoData,
    Threshold,
    ThresholdResult,
    ThresholdSet,
)

GOLDEN_DIR = Path(__file__).resolve().parent / "evaluation_golden"
RELEASE_THRESHOLDS_FILE = GOLDEN_DIR / "release-thresholds-v1.json"
RELEASE_THRESHOLDS_VERSION = "release-thresholds-v1"


def _bound(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise FixtureError(f"{where}: bound must be a decimal string (exact), not {type(value).__name__}")
    try:
        exact = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise FixtureError(f"{where}: bound {value!r} is not a decimal number") from error
    if not 0 <= exact <= 1:
        raise FixtureError(f"{where}: bound {value!r} is outside [0, 1] (every metric is a rate)")
    return value


def parse_thresholds(document: Mapping[str, Any]) -> ThresholdSet:
    if not isinstance(document, Mapping) or document.get("schema") != THRESHOLD_SCHEMA_VERSION:
        raise FixtureError(f"thresholds: schema must be {THRESHOLD_SCHEMA_VERSION!r}")
    if set(document) - {"schema", "version", "thresholds"}:
        raise FixtureError(f"thresholds: unknown keys {sorted(set(document) - {'schema', 'version', 'thresholds'})}")
    version = document.get("version")
    if not isinstance(version, str) or not version:
        raise FixtureError("thresholds: version is required")
    rows = document.get("thresholds")
    if not isinstance(rows, list):
        raise FixtureError("thresholds: thresholds must be a list")
    parsed: list[Threshold] = []
    for index, row in enumerate(rows):
        where = f"thresholds[{index}]"
        if not isinstance(row, Mapping) or set(row) - {"metric", "comparator", "bound", "on_no_data", "rationale"}:
            raise FixtureError(f"{where}: unknown or missing keys")
        if row.get("metric") not in METRIC_NAMES:
            raise FixtureError(f"{where}: unknown metric {row.get('metric')!r}")
        try:
            comparator, on_no_data = Comparator(str(row.get("comparator"))), NoData(str(row.get("on_no_data", "fail")))
        except ValueError as error:
            raise FixtureError(f"{where}: {error}") from error
        rationale = row.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise FixtureError(f"{where}: every threshold needs a written rationale")
        parsed.append(Threshold(str(row["metric"]), comparator, _bound(row.get("bound"), where), on_no_data, rationale))
    names = [threshold.metric for threshold in parsed]
    if sorted(names) != sorted(METRIC_NAMES) or len(set(names)) != len(names):
        raise FixtureError(f"thresholds: every metric needs exactly one threshold (missing {sorted(set(METRIC_NAMES) - set(names))}, "
                           f"repeated {sorted({n for n in names if names.count(n) > 1})})")
    return ThresholdSet(version, tuple(sorted(parsed, key=lambda threshold: METRIC_NAMES.index(threshold.metric))))


def load_thresholds(path: Path = RELEASE_THRESHOLDS_FILE) -> ThresholdSet:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FixtureError(f"{path.name}: {error}") from error
    return parse_thresholds(document)


def release_thresholds() -> ThresholdSet:
    thresholds = load_thresholds()
    if thresholds.version != RELEASE_THRESHOLDS_VERSION:
        raise FixtureError(f"{RELEASE_THRESHOLDS_FILE.name}: version {thresholds.version!r} is not {RELEASE_THRESHOLDS_VERSION!r}")
    if any(threshold.on_no_data != NoData.FAIL for threshold in thresholds.thresholds):
        raise FixtureError(f"{RELEASE_THRESHOLDS_FILE.name}: a release threshold must fail on no data")
    return thresholds


def check(threshold: Threshold, value: Fraction | None) -> ThresholdResult:
    if value is None:
        return ThresholdResult(threshold, None, threshold.on_no_data == NoData.PASS, True)
    bound = threshold.exact_bound
    passed = value >= bound if threshold.comparator == Comparator.AT_LEAST else value <= bound
    return ThresholdResult(threshold, value, passed, False)


def evaluate_thresholds(metrics: Sequence[EvaluationMetric], thresholds: ThresholdSet) -> tuple[ThresholdResult, ...]:
    values = {metric.name: metric.value for metric in metrics}
    missing = [threshold.metric for threshold in thresholds.thresholds if threshold.metric not in values]
    if missing:
        raise ValueError(f"no metric computed for thresholds {missing}")
    return tuple(check(threshold, values[threshold.metric]) for threshold in thresholds.thresholds)
