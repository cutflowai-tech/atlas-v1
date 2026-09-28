from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import FormatChecker
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


def _schemas() -> dict[str, dict[str, Any]]:
    return {path.name: json.loads(path.read_text()) for path in CONTRACTS.glob("*.schema.json")}


def _registry(schemas: dict[str, dict[str, Any]]) -> Registry[Any]:
    registry: Registry[Any] = Registry()
    for schema in schemas.values():
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(schema["$id"], resource)
        registry = registry.with_resource(Path(schema["$id"]).name, resource)
    return registry


def schema_errors(instance: Any, schema_name: str) -> list[str]:
    schemas = _schemas()
    schema = schemas[schema_name]
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    validator = validator_class(schema, registry=_registry(schemas), format_checker=FormatChecker())
    return [error.message for error in sorted(validator.iter_errors(instance), key=lambda item: list(item.path))]


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def semantic_codes(instance: Any, schema_name: str) -> list[str]:
    if isinstance(instance, list):
        event_ids = [event.get("event_id") for event in instance if isinstance(event, dict)]
        return ["DUPLICATE_EVENT"] if len(event_ids) != len(set(event_ids)) else []
    if not isinstance(instance, dict):
        return []
    if schema_name == "work-cycle.schema.json":
        codes = []
        if instance.get("requested_eta") is None:
            codes.append("MISSING_REQUESTED_ETA")
        start = instance.get("in_progress_at")
        end = instance.get("ready_for_approval_at")
        if start and end and _timestamp(end) <= _timestamp(start):
            codes.append("END_BEFORE_START")
        if start and end and instance.get("duration_seconds") != int((_timestamp(end) - _timestamp(start)).total_seconds()):
            codes.append("DURATION_MISMATCH")
        return codes
    if schema_name == "speed-metric.schema.json" and instance.get("video_type") != instance.get("cohort_video_type"):
        return ["CROSS_VIDEO_TYPE_COHORT"]
    if schema_name == "deadline-metric-v1.1.schema.json" and instance.get("ready_for_approval_at") and instance.get("requested_eta"):
        codes = []
        delta = int((_timestamp(instance["ready_for_approval_at"]) - _timestamp(instance["requested_eta"])).total_seconds())
        if instance.get("delta_seconds") != delta:
            codes.append("DEADLINE_DELTA_MISMATCH")
        expected = "early" if delta < 0 else "on_time" if delta == 0 else "late"
        if instance.get("result") != expected:
            codes.append("DEADLINE_RESULT_MISMATCH")
        return codes
    if schema_name == "deadline-metric.schema.json" and instance.get("ready_for_approval_at") and instance.get("requested_eta"):
        expected = "on_time" if _timestamp(instance["ready_for_approval_at"]) <= _timestamp(instance["requested_eta"]) else "late"
        if instance.get("result") != expected:
            return ["DEADLINE_RESULT_MISMATCH"]
    if schema_name == "normalized-status-event.schema.json" and instance.get("actor_resolution") == "unresolved_waset_co":
        return ["UNRESOLVED_ACTOR"]
    return []


def validate(instance: Any, schema_name: str) -> list[str]:
    if isinstance(instance, list):
        nested = [message for item in instance for message in schema_errors(item, schema_name)]
        return (["SCHEMA_INVALID"] if nested else []) + semantic_codes(instance, schema_name)
    return (["SCHEMA_INVALID"] if schema_errors(instance, schema_name) else []) + semantic_codes(instance, schema_name)


def assert_valid(instance: Any, schema_name: str) -> None:
    errors = schema_errors(instance, schema_name) + semantic_codes(instance, schema_name)
    if errors:
        raise ValidationError("; ".join(errors))
