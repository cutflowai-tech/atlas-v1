"""Deterministic mapping of Intelligence V2 findings to reasoning cases (``REV/04`` #7–#9).

Every published finding is mapped by an explicit rule (``TOPIC_RULES``, keyed by finding type) to one stable identity: its
subject comes from the finding's scope, its topic from the finding type and, where one type covers several topics, from one
categorical statement parameter (for example ``change.editor`` with ``measure = late_rate`` is a deadline topic, with
``measure = median_execution`` a speed topic). Several findings about the same subject and topic become **one** case — for example
an Editor's late-rate deterioration, their mix-adjusted lateness and a contradiction qualifying their late headline are all the
Editor's deadline case. The LLM never clusters findings.

Within a case each finding has a ``member_key``: its type, its scope and its categorical discriminators (the statement parameters
named in ``DISCRIMINATORS``, and its supporting evidence kinds). It is stable across runs while the finding keeps reporting the
same thing, whatever its values, window or ``finding_id``. Two findings of one case with the same member key would be ambiguous;
that never happens with the current detectors (tested) and, if it ever did, the second one is keyed with a content hash and the
mapping reports a warning.

A finding of a type without a rule, or with a parameter value the rule does not know, is never guessed: it is returned in
``CaseMapping.unmapped`` with the reason. ``tests/test_reasoning_case_identity.py`` requires a rule for every registered detector.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from atlas_reasoning.case_identity import CaseIdentity, CaseIdentityError, assert_no_collisions, build_identity
from atlas_reasoning.enums import CaseType, SubjectType, TopicKey
from atlas_reasoning.frozen import thaw
from atlas_reasoning.reasoning_input_boundary import ReasoningInput, UpstreamFinding

MAPPING_VERSION = "case-mapping-v1"
# Categorical statement parameters that tell two findings of one type apart. Never numbers, dates or wording.
DISCRIMINATORS = ("measure", "against", "outcome", "dimension", "value", "label", "label_class", "verdict", "signal", "test", "headline", "group",
                  "cohort_key", "code")
DATA_SOURCE_ID = "monday"

SUBJECT_BY_SCOPE = {"editor": SubjectType.EDITOR, "team": SubjectType.TEAM, "video_type": SubjectType.VIDEO_TYPE, "stage": SubjectType.WORKFLOW_STAGE,
                    "project": SubjectType.PROJECT, "data": SubjectType.DATA_SOURCE}
CASE_TYPE_BY_SUBJECT = {SubjectType.EDITOR: CaseType.EDITOR_PATTERN, SubjectType.TEAM: CaseType.TEAM_PATTERN,
                        SubjectType.VIDEO_TYPE: CaseType.VIDEO_TYPE_PATTERN, SubjectType.WORKFLOW_STAGE: CaseType.WORKFLOW_PATTERN,
                        SubjectType.PROJECT: CaseType.PROJECT_RISK, SubjectType.DATA_SOURCE: CaseType.DATA_QUALITY}


class UnmappedFinding(Exception):
    pass


@dataclass(frozen=True)
class TopicRule:
    """How one finding type becomes a case identity."""

    topic: Callable[[UpstreamFinding], TopicKey]
    case_type: CaseType | None = None                  # None: from the subject (CASE_TYPE_BY_SUBJECT)
    dimensions: Callable[[UpstreamFinding], dict[str, str]] = field(default=lambda finding: {})
    description: str = ""


def _param(finding: UpstreamFinding, name: str) -> Any:
    for statement in finding.statements:
        if name in statement.params:
            return statement.params[name]
    return None


def _required(finding: UpstreamFinding, name: str) -> str:
    value = _param(finding, name)
    if not isinstance(value, str) or not value:
        raise UnmappedFinding(f"{finding.finding_type}: no {name} parameter")
    return value


def _by(name: str, table: Mapping[str, TopicKey]) -> Callable[[UpstreamFinding], TopicKey]:
    def resolve(finding: UpstreamFinding) -> TopicKey:
        value = _param(finding, name)
        if value not in table:
            raise UnmappedFinding(f"{finding.finding_type}: {name}={value!r} has no topic rule")
        return table[value]
    return resolve


def _fixed(topic: TopicKey) -> Callable[[UpstreamFinding], TopicKey]:
    return lambda finding: topic


MEASURE_TOPICS = {"late_rate": TopicKey.DEADLINE, "median_execution": TopicKey.SPEED, "negative_label_rate": TopicKey.QUALITY}
OUTCOME_TOPICS = {"late_delivery": TopicKey.DEADLINE, "not_late_delivery": TopicKey.DEADLINE, "negative_quality_label": TopicKey.QUALITY,
                  "positive_quality_label": TopicKey.QUALITY}
SHARED_TOPICS = {"late_delivery": TopicKey.DEADLINE, "late_rate": TopicKey.DEADLINE, "short_runway": TopicKey.RUNWAY}

TOPIC_RULES: dict[str, TopicRule] = {
    "change.editor": TopicRule(_by("measure", MEASURE_TOPICS), description="An Editor against their own history: the measure names the topic"),
    "change.team": TopicRule(_by("measure", MEASURE_TOPICS), description="The team against its history: the measure names the topic"),
    "change.video_type": TopicRule(_by("measure", MEASURE_TOPICS), description="A Video Type's execution time over time"),
    "person.mix_adjusted_deadline": TopicRule(_fixed(TopicKey.DEADLINE), description="An Editor's lateness on the team's mix"),
    "contradiction.bad_headline": TopicRule(_fixed(TopicKey.DEADLINE), description="Deeper evidence qualifying a late headline"),
    "contradiction.metric_conflict": TopicRule(_fixed(TopicKey.COMPONENT_CONFLICT), description="Component states pointing in opposite directions"),
    "contradiction.hidden_risk": TopicRule(_fixed(TopicKey.HIDDEN_SIGNAL), description="A favourable headline hiding another signal"),
    "concentration.negative": TopicRule(_by("outcome", OUTCOME_TOPICS), description="Adverse outcomes concentrated in one group"),
    "concentration.positive": TopicRule(_by("outcome", OUTCOME_TOPICS), description="Favourable outcomes concentrated in one group"),
    "pattern.shared_across_editors": TopicRule(_by("measure", SHARED_TOPICS), description="Elevated lateness or short runway across Editors"),
    "pattern.repeated_delay": TopicRule(_fixed(TopicKey.DEADLINE), description="Repeated late combinations in a Video Type"),
    "pattern.repeated_quality": TopicRule(_fixed(TopicKey.QUALITY), description="A repeated Negative label in a Video Type"),
    "pattern.time": TopicRule(_fixed(TopicKey.DEADLINE), description="Lateness by weekday or period of the month"),
    "editor.speed_pattern": TopicRule(_fixed(TopicKey.SPEED), description="An Editor's approved Speed verdicts"),
    "editor.label_pattern": TopicRule(_fixed(TopicKey.QUALITY), description="Where an Editor's labels sit"),
    "workload.association": TopicRule(_fixed(TopicKey.WORKLOAD), description="Workload associated with outcomes"),
    "workload.overload_pattern": TopicRule(_fixed(TopicKey.WORKLOAD), description="Repeated overload inside one Editor's work"),
    "bottleneck.pre_editor_runway": TopicRule(_fixed(TopicKey.RUNWAY), description="Lateness that starts before editor execution"),
    "bottleneck.post_editor": TopicRule(_fixed(TopicKey.POST_EDITOR_DELAY), description="Delay after the Editor's interval"),
    "workflow.time_map": TopicRule(_fixed(TopicKey.WORKFLOW_TIME), description="Where elapsed project time is spent"),
    "risk.open_work": TopicRule(_fixed(TopicKey.OPEN_WORK_RISK), CaseType.OPEN_WORK_RISK, lambda finding: {"signal": _required(finding, "signal")},
                                "One risk signal on current open work"),
    "risk.historical_similarity": TopicRule(_fixed(TopicKey.OPEN_WORK_RISK), CaseType.PROJECT_RISK,
                                            description="An open project compared with similar past projects"),
}
DATA_RULE = TopicRule(_fixed(TopicKey.DATA_QUALITY), CaseType.DATA_QUALITY,
                      lambda finding: {"signal": finding.finding_type.split(".", 1)[1]}, "One data warning (data.<code>)")


def rule_for(finding_type: str) -> TopicRule | None:
    if finding_type.startswith("data."):
        return DATA_RULE
    return TOPIC_RULES.get(finding_type)


def subject_of(finding: UpstreamFinding) -> tuple[SubjectType, str | None]:
    scope = finding.scope
    subject = SUBJECT_BY_SCOPE.get(scope.kind)
    if subject is None:
        raise UnmappedFinding(f"{finding.finding_type}: scope {scope.kind!r} has no subject")
    subject_id = {SubjectType.EDITOR: scope.editor_id, SubjectType.TEAM: "team", SubjectType.VIDEO_TYPE: scope.cohort_key,
                  SubjectType.WORKFLOW_STAGE: scope.stage, SubjectType.PROJECT: scope.monday_item_id, SubjectType.DATA_SOURCE: DATA_SOURCE_ID}[subject]
    return subject, subject_id


def identity_of(finding: UpstreamFinding) -> CaseIdentity:
    rule = rule_for(finding.finding_type)
    if rule is None:
        raise UnmappedFinding(f"{finding.finding_type}: no topic rule")
    subject, subject_id = subject_of(finding)
    if subject_id is None:
        raise UnmappedFinding(f"{finding.finding_type}: scope {finding.scope.kind!r} names no {subject.value}")
    try:
        return build_identity(subject, subject_id, rule.topic(finding), rule.case_type or CASE_TYPE_BY_SUBJECT[subject], rule.dimensions(finding))
    except CaseIdentityError as error:
        raise UnmappedFinding(f"{finding.finding_type}: {error}") from None


def member_key(finding: UpstreamFinding) -> str:
    """Stable key of one finding inside its case: type, scope and categorical discriminators — never values, windows or IDs."""
    scope = finding.scope
    scope_part = ";".join(f"{name}={value}" for name, value in (("kind", scope.kind), ("editor_id", scope.editor_id), ("cohort_key", scope.cohort_key),
                                                                ("stage", scope.stage), ("monday_item_id", scope.monday_item_id)) if value is not None)
    codes = ",".join(sorted({block.code for block in finding.supporting_evidence}))
    discriminators = ";".join(f"{name}={value}" for name in DISCRIMINATORS if isinstance(value := _param(finding, name), (str, bool)))
    first = finding.statements[0].code if finding.statements else ""
    return f"{finding.finding_type}|{scope_part}|{codes}|{discriminators}|{first}"


@dataclass(frozen=True)
class Contribution:
    member_key: str
    finding: UpstreamFinding


@dataclass(frozen=True)
class CaseCandidate:
    """One case in one snapshot: its identity and the findings that contribute to it, ordered by member key."""

    identity: CaseIdentity
    contributions: tuple[Contribution, ...]

    @property
    def case_id(self) -> str:
        return self.identity.case_id


@dataclass(frozen=True)
class CaseMapping:
    mapping_version: str
    candidates: tuple[CaseCandidate, ...]
    unmapped: tuple[Mapping[str, str], ...]
    warnings: tuple[str, ...]

    def by_case_id(self) -> dict[str, CaseCandidate]:
        return {candidate.case_id: candidate for candidate in self.candidates}


def map_findings(findings: Iterable[UpstreamFinding]) -> CaseMapping:
    """Group findings into case candidates. Independent of input order; the same findings always give the same candidates."""
    groups: dict[str, list[Contribution]] = {}
    identities: list[CaseIdentity] = []
    unmapped: list[dict[str, str]] = []
    warnings: list[str] = []
    ordered = sorted(findings, key=lambda finding: (finding.finding_type, member_key(finding), _content_hash(finding)))
    for finding in ordered:
        try:
            identity = identity_of(finding)
        except UnmappedFinding as error:
            unmapped.append({"finding_id": finding.finding_id, "finding_type": finding.finding_type, "reason": str(error)})
            continue
        identities.append(identity)
        members = groups.setdefault(identity.case_id, [])
        key = member_key(finding)
        if any(existing.member_key == key for existing in members):
            warnings.append(f"{identity.case_id}: two findings share member key {key!r}; the second is keyed by content")
            key = f"{key}#{_content_hash(finding)}"
        members.append(Contribution(key, finding))
    by_id = assert_no_collisions(identities)
    candidates = tuple(CaseCandidate(by_id[case_id], tuple(sorted(members, key=lambda row: row.member_key))) for case_id, members in sorted(groups.items()))
    return CaseMapping(MAPPING_VERSION, candidates, tuple(sorted(unmapped, key=lambda row: (row["finding_type"], row["finding_id"]))), tuple(warnings))


def map_cases(payload: ReasoningInput) -> CaseMapping:
    return map_findings(payload.findings)


def _content_hash(finding: UpstreamFinding) -> str:
    body = json.dumps([[s.level, s.code, thaw(s.params)] for s in finding.statements], sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:12]
