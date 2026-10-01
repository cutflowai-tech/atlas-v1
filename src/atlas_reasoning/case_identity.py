"""Deterministic, stable case identity (``REV/04``).

``case_id`` answers *what management issue is this about?* It is built only from stable semantic dimensions:

    subject_type, subject_id, topic_key  [+ the optional dimensions the topic rule declares: video_type, workflow_stage,
                                            detector_family, signal]

and never from rates, counts, dates, confidence, wording, finding order, Intelligence V2 ``finding_id`` (which changes with the
analysis window), evidence values, request IDs or anything an LLM produced. The LLM never creates or alters a case identity.

Construction:

1. every component is normalized: Unicode NFC, surrounding whitespace removed, inner whitespace collapsed to one space, lower case;
   an empty component is invalid;
2. the components are percent-encoded and joined into the ``identity_key``
   (``case-identity-v1|editor|editor-label-12|deadline`` plus ``|signal=past_eta`` etc. in a fixed dimension order) — an injective
   encoding, so two different identities never share a key;
3. ``case_id = "rc1_" + sha256(identity_key)[:32]`` (128 bits).

Collision handling: a run refuses two different identity keys with the same ``case_id`` (``CaseIdentityCollision``), and the
database refuses a ``case_id`` or ``identity_key`` already stored with another identity (``reasoning_cases`` primary key and unique
key, ``store.repository.insert_case``). With 128 bits a collision is not expected; if one ever happened it would stop the run rather
than merge two issues.

A new case (instead of an update of an existing one) is created exactly when the subject, the topic or a rule-declared dimension
differs. A change of Intelligence V2 finding types *within* a topic, of evidence, of confidence or of the analysis window updates
the existing case. Changing the identity rules themselves requires a new ``IDENTITY_VERSION``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from atlas_reasoning.enums import CaseType, IdentityDimension, SubjectType, TopicKey

IDENTITY_VERSION = "case-identity-v1"
CASE_ID_PREFIX = "rc1_"
_DIMENSION_ORDER = (IdentityDimension.VIDEO_TYPE, IdentityDimension.WORKFLOW_STAGE, IdentityDimension.DETECTOR_FAMILY, IdentityDimension.SIGNAL)
_SPACE = re.compile(r"\s+")


class CaseIdentityError(ValueError):
    """A case identity is incomplete or invalid."""


class CaseIdentityCollision(CaseIdentityError):
    """Two different identity keys produced the same case_id."""


def normalize_component(value: Any) -> str:
    if value is None:
        raise CaseIdentityError("an identity component is missing")
    text = _SPACE.sub(" ", unicodedata.normalize("NFC", str(value))).strip().lower()
    if not text:
        raise CaseIdentityError("an identity component is empty")
    return text


def _encode(value: str) -> str:
    return quote(value, safe="-._~")


@dataclass(frozen=True)
class CaseIdentity:
    subject_type: SubjectType
    subject_id: str
    topic_key: TopicKey
    case_type: CaseType
    dimensions: Mapping[str, str]

    @property
    def identity_key(self) -> str:
        parts = [IDENTITY_VERSION, _encode(self.subject_type.value), _encode(self.subject_id), _encode(self.topic_key.value)]
        parts += [f"{name.value}={_encode(self.dimensions[name.value])}" for name in _DIMENSION_ORDER if name.value in self.dimensions]
        return "|".join(parts)

    @property
    def case_id(self) -> str:
        return CASE_ID_PREFIX + hashlib.sha256(self.identity_key.encode()).hexdigest()[:32]

    def to_dict(self) -> dict[str, Any]:
        return {"identity_version": IDENTITY_VERSION, "identity_key": self.identity_key, "case_id": self.case_id, "case_type": self.case_type.value,
                "subject_type": self.subject_type.value, "subject_id": self.subject_id, "topic_key": self.topic_key.value,
                "identity_dimensions": dict(sorted(self.dimensions.items()))}


def build_identity(subject_type: SubjectType | str, subject_id: Any, topic_key: TopicKey | str, case_type: CaseType | str,
                   dimensions: Mapping[str, Any] | None = None) -> CaseIdentity:
    """Normalize and validate the identity dimensions. Unknown dimension names and empty values are errors."""
    try:
        subject = SubjectType(subject_type)
        topic = TopicKey(topic_key)
        kind = CaseType(case_type)
    except ValueError as error:
        raise CaseIdentityError(str(error)) from None
    allowed = {name.value for name in IdentityDimension}
    dims: dict[str, str] = {}
    for name, value in (dimensions or {}).items():
        if name not in allowed:
            raise CaseIdentityError(f"{name!r} is not an identity dimension")
        dims[name] = normalize_component(value)
    return CaseIdentity(subject, normalize_component(subject_id), topic, kind, dims)


def assert_no_collisions(identities: Iterable[CaseIdentity]) -> dict[str, CaseIdentity]:
    """case_id -> identity, refusing two different identity keys with one case_id."""
    seen: dict[str, CaseIdentity] = {}
    for identity in identities:
        other = seen.setdefault(identity.case_id, identity)
        if other.identity_key != identity.identity_key:
            raise CaseIdentityCollision(f"{identity.case_id} is produced by {other.identity_key!r} and {identity.identity_key!r}")
    return seen


def identity_errors(case: Mapping[str, Any]) -> list[str]:
    """Contract check (registered in ``contracts.CASE_CHECKS``): a case's identity fields and case_id follow from its dimensions."""
    try:
        identity = build_identity(case["subject_type"], case["subject_id"], case["topic_key"], case["case_type"], case["identity_dimensions"])
    except CaseIdentityError as error:
        return [f"CASE_ID_MISMATCH: invalid identity: {error}"]
    errors = []
    if case["identity_version"] != IDENTITY_VERSION:
        errors.append(f"CASE_ID_MISMATCH: identity_version {case['identity_version']} is not {IDENTITY_VERSION}")
    if case["subject_id"] != identity.subject_id or dict(case["identity_dimensions"]) != dict(identity.dimensions):
        errors.append("CASE_ID_MISMATCH: identity components are not normalized")
    if case["identity_key"] != identity.identity_key:
        errors.append(f"CASE_ID_MISMATCH: identity_key should be {identity.identity_key!r}")
    if case["case_id"] != identity.case_id:
        errors.append(f"CASE_ID_MISMATCH: case_id should be {identity.case_id}")
    return errors
