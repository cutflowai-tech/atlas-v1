"""Deep-immutable copies of JSON-like data, and their plain JSON-ready inverse.

``freeze`` copies its input: dicts become read-only ``MappingProxyType`` views of a private copy, lists and tuples become tuples,
sets become sorted tuples. Nothing reachable from a frozen value aliases the caller's objects, so code holding a frozen value can
neither mutate it nor, through it, the upstream document it came from.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

FrozenMap = Mapping[str, Any]

EMPTY_MAP: FrozenMap = MappingProxyType({})


def freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(freeze(item) for item in value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"cannot freeze a {type(value).__name__}: only JSON-like values cross the reasoning boundary")


def freeze_map(value: Mapping[str, Any] | None) -> FrozenMap:
    return freeze(value) if value else EMPTY_MAP


def thaw(value: Any) -> Any:
    """A plain, JSON-ready copy (dicts and lists) of a frozen value."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value
