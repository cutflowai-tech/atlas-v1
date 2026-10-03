"""Structured-output descriptions for provider requests (``REV/06`` #4).

``contract_output(schema_file)`` asks the model for JSON matching a Reasoning V3 contract schema: the provider receives a
self-contained copy (every ``$ref`` inlined), and the response is validated locally against the real contract schema
(``contracts.schema_errors``). ``schema_output(name, schema)`` does the same for an ad-hoc schema (the health check).

Prompt-specific output shapes (Phase 07's analyst output, Phase 08's patch output) are built on these helpers by their phases.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from jsonschema import FormatChecker
from jsonschema.validators import validator_for

from atlas_reasoning import contracts
from atlas_reasoning.frozen import freeze
from atlas_reasoning.provider import StructuredOutput


def _resolve(ref: str, current: str) -> tuple[dict[str, Any], str]:
    file, _, pointer = ref.partition("#")
    file = file or current
    node: Any = contracts.schema(file)
    for part in [p for p in pointer.split("/") if p]:
        node = node[part]
    return node, file


def inline_schema(schema_file: str) -> dict[str, Any]:
    """A copy of a contract schema with every ``$ref`` replaced by its target (the reasoning schemas have no recursion)."""

    def walk(node: Any, current: str, depth: int = 0) -> Any:
        if depth > 50:
            raise ValueError(f"{schema_file}: $ref nesting too deep")
        if isinstance(node, Mapping):
            if "$ref" in node:
                target, file = _resolve(str(node["$ref"]), current)
                merged = {**copy.deepcopy(target), **{k: v for k, v in node.items() if k != "$ref"}}
                return walk(merged, file, depth + 1)
            return {key: walk(value, current, depth + 1) for key, value in node.items() if key not in ("$schema", "$id", "$defs")}
        if isinstance(node, list):
            return [walk(item, current, depth + 1) for item in node]
        return node

    inlined: dict[str, Any] = walk(contracts.schema(schema_file), schema_file)
    return inlined


def contract_output(schema_file: str, name: str | None = None) -> StructuredOutput:
    return StructuredOutput(name or schema_file.removesuffix(".schema.json").replace("-", "_"), freeze(inline_schema(schema_file)),
                            lambda value: contracts.schema_errors(value, schema_file))


def schema_output(name: str, schema: Mapping[str, Any]) -> StructuredOutput:
    validator = validator_for(schema)(schema, format_checker=FormatChecker())
    return StructuredOutput(name, freeze(schema), lambda value: [error.message for error in validator.iter_errors(value)])
