"""Reasoning V3 release metadata and release eligibility (Phase 20-A, ``REV/20`` #11).

    metadata = release_metadata(commit="<40-hex sha>", env=os.environ)     # what this release is: code, model, prompts, contracts, ...
    metadata.missing()                                                   # [] when complete
    eligibility(evaluation_run_json, metadata, rollout_config(env))     # may this release go forward (input to Phase 20 verification)?

Every field is **derived from code** (the version constants the modules own, the migrations directory, the published Phase 19 golden
digest and thresholds) or from validated configuration (the effective model, the rollout state). Nothing is free-form, and nothing is
a secret: no key, no password, no URL, no file path. The representation is deterministic (sorted, no timestamp): the same release gives
the same bytes.

Eligibility does **not** evaluate anything. Phase 19 is the release-evaluation authority: eligibility checks that a Phase 19 runner
result (``python -m atlas_reasoning evaluate run`` JSON) is a release PASS whose stored verdicts agree with it, that its embedded
report matches its ``report_sha256`` (a checksum: it detects corruption or truncation, it does not authenticate the file — keep the
run JSON with the release record), and that it evaluated *this* software (the report's versions equal this code's) on the pinned model.
It then checks that the metadata is complete and that the rollout configuration is valid. It never recomputes a metric and never reads
a threshold value. It is a repository-side input: the live-model run, the human review and the stage approval remain (``OUTSTANDING``).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from atlas_reasoning import REASONING_PACKAGE_VERSION, analyst, executive, executive_contracts, executive_validator, guardrails, reviewer, settings, updater
from atlas_reasoning.enums import CONTRACT_VERSION
from atlas_reasoning.evaluation import PUBLISHED_FIXTURE_DIGEST, software_versions
from atlas_reasoning.evaluation_thresholds import RELEASE_THRESHOLDS_VERSION
from atlas_reasoning.evaluation_types import EVALUATION_SCHEMA_VERSION
from atlas_reasoning.rollout import ROLLOUT_VERSION, RolloutConfig
from atlas_reasoning.store.migrate import available_migrations

METADATA_VERSION = "reasoning-release-metadata-v1"
RUNNER_SCHEMA = "reasoning-evaluation-run-v1"           # evaluation_runner.RUNNER_SCHEMA (not imported: no runner dependency here)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
REQUIRED = ("metadata_version", "commit", "reasoning_package", "reasoning_contract", "executive_contract", "model", "pinned_model",
            "analyst_prompt", "update_prompt", "executive_prompt", "reviewer_prompt", "guardrails_validator", "executive_validator",
            "evaluation_schema", "golden_fixture_digest", "release_thresholds", "latest_migration", "migrations", "migrations_sha256",
            "rollout_version", "rollout", "software_versions")


@dataclass(frozen=True)
class ReleaseMetadata:
    fields: Mapping[str, Any] = field(default_factory=dict)

    def missing(self) -> list[str]:
        """Required fields that are absent or empty (a release with any is not identifiable)."""
        return [name for name in REQUIRED if self.fields.get(name) in (None, "", [], {})]

    @property
    def complete(self) -> bool:
        return not self.missing()

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.to_json())

    def to_json(self) -> str:
        return json.dumps(dict(self.fields), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def release_metadata(*, commit: str | None, env: Mapping[str, str], rollout: RolloutConfig | None = None) -> ReleaseMetadata:
    """The metadata of the release at ``commit`` (the repository commit, 40 hex; None or malformed leaves the field empty, so the
    metadata is incomplete rather than wrong). ``env`` supplies the effective model and, unless ``rollout`` is given, the rollout."""
    from atlas_reasoning.rollout import rollout_config

    migrations = [migration.name for migration in available_migrations()]
    state = rollout if rollout is not None else rollout_config(env)
    return ReleaseMetadata({
        "metadata_version": METADATA_VERSION,
        "commit": commit if commit and _COMMIT.fullmatch(commit) else None,
        "reasoning_package": REASONING_PACKAGE_VERSION,
        "reasoning_contract": CONTRACT_VERSION,
        "executive_contract": executive_contracts.BRIEF_CONTRACT_VERSION,
        "model": settings.gateway_settings(env).model,           # validated: the pinned model unless an explicit override is on
        "pinned_model": settings.PINNED_MODEL,
        "model_override": settings.gateway_settings(env).model != settings.PINNED_MODEL,
        "analyst_prompt": analyst.ANALYST_PROMPT_VERSION,
        "update_prompt": updater.UPDATE_PROMPT_VERSION,
        "executive_prompt": executive.EXECUTIVE_PROMPT_VERSION,
        "reviewer_prompt": reviewer.REVIEWER_PROMPT_VERSION,
        "guardrails_validator": guardrails.VALIDATOR_VERSION,
        "executive_validator": executive_validator.VALIDATOR_VERSION,
        "evaluation_schema": EVALUATION_SCHEMA_VERSION,
        "golden_fixture_digest": PUBLISHED_FIXTURE_DIGEST,
        "release_thresholds": RELEASE_THRESHOLDS_VERSION,
        "latest_migration": migrations[-1] if migrations else None,
        "migrations": migrations,
        "migrations_sha256": hashlib.sha256("\n".join(migrations).encode()).hexdigest() if migrations else None,
        "rollout_version": ROLLOUT_VERSION,
        "rollout": state.to_dict(),
        "software_versions": software_versions(),
    })


# What eligibility does not establish (it is a repository-side input, not release approval): the final approval also weighs these.
OUTSTANDING = ("a live-model Phase 19 evaluation run (Phase 19-B live mode; operator-approved, budgeted)",
               "a completed human management-quality review bound to the evaluation report (evaluate review-validate)",
               "explicit approval of the rollout stage, the deployment and any access change")


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reasons: tuple[str, ...]
    evaluation_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"eligible": self.eligible, "reasons": list(self.reasons), "scope": "repository release eligibility: a Phase 19 release PASS of "
                "this software, complete metadata, a valid rollout", "evaluation_mode": self.evaluation_mode, "outstanding": list(OUTSTANDING)}


def eligibility(evaluation_run: Mapping[str, Any] | None, metadata: ReleaseMetadata, rollout: RolloutConfig) -> Eligibility:
    """Whether this release may go forward: a Phase 19 release PASS for this software, complete metadata and a valid rollout (``rollout``
    is a ``RolloutConfig``, which cannot exist invalid). ``reasons`` lists every failed condition (empty when eligible)."""
    reasons: list[str] = []
    run = evaluation_run if isinstance(evaluation_run, Mapping) else {}
    report = run.get("report") if isinstance(run.get("report"), Mapping) else None
    if not run:
        reasons.append("evaluation: no Phase 19 evaluation result")
    elif run.get("schema") != RUNNER_SCHEMA:
        reasons.append(f"evaluation: not a {RUNNER_SCHEMA} result")
    elif run.get("code") != "PASS" or run.get("result") != "PASS" or run.get("exit_code") != 0 or report is None:
        reasons.append(f"evaluation: Phase 19 result is {run.get('code')!r}, not PASS")
    else:
        canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        coverage = report.get("coverage") if isinstance(report.get("coverage"), Mapping) else {}
        thresholds = report.get("thresholds") if isinstance(report.get("thresholds"), Mapping) else {}
        if hashlib.sha256(canonical.encode()).hexdigest() != run.get("report_sha256"):
            reasons.append("evaluation: the report does not match its report_sha256 (altered or truncated)")
        if report.get("result") != "PASS" or coverage.get("release_conformant") is not True or coverage.get("missing"):
            reasons.append("evaluation: the report is not a release-conformant PASS with full coverage")
        verdicts = report.get("threshold_results") if isinstance(report.get("threshold_results"), list) else []
        if not verdicts or not all(isinstance(row, Mapping) and row.get("passed") is True for row in verdicts) or report.get("failures"):
            reasons.append("evaluation: the report's own threshold verdicts and failures do not support its PASS")
        if thresholds.get("version") != metadata.fields.get("release_thresholds"):
            reasons.append("evaluation: evaluated against other release thresholds")
        if coverage.get("fixture_digest") != metadata.fields.get("golden_fixture_digest"):
            reasons.append("evaluation: evaluated other golden cases")
        if report.get("versions") != metadata.fields.get("software_versions"):
            reasons.append("evaluation: evaluated different software versions than this release")
    reasons += [f"metadata: missing {name}" for name in metadata.missing()]
    if metadata.fields.get("model_override") is not False or metadata.fields.get("model") != metadata.fields.get("pinned_model"):
        reasons.append("model: the release runs an overridden model; Phase 19 evaluates the pinned model only")
    if metadata.fields.get("rollout") != rollout.to_dict():
        reasons.append("rollout: the metadata does not describe this rollout configuration")
    mode = run.get("mode")
    return Eligibility(not reasons, tuple(reasons), mode if isinstance(mode, str) else None)
