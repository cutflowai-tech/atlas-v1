"""Every registered Intelligence V2 detector, in the brief's implementation order (Task 74: the detector catalog)."""

from __future__ import annotations

from typing import Any

from atlas_commander.investigation import (
    bottlenecks,
    changes,
    concentration,
    contradictions,
    data_quality,
    editor,
    patterns,
    person_system,
    risks,
    workload,
)
from atlas_commander.investigation.context import Detector

DETECTORS: tuple[Detector, ...] = (
    *concentration.DETECTORS,
    *bottlenecks.DETECTORS,
    *changes.DETECTORS,
    *workload.DETECTORS,
    *patterns.DETECTORS,
    *person_system.DETECTORS,
    *contradictions.DETECTORS,
    *risks.DETECTORS,
    *editor.DETECTORS,
    *data_quality.DETECTORS,
)


def catalog() -> list[dict[str, Any]]:
    return [detector.catalog_entry() for detector in DETECTORS]


def by_id(detector_id: str) -> Detector:
    return next(detector for detector in DETECTORS if detector.detector_id == detector_id)
