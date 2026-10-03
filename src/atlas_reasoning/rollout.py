"""Reasoning V3 rollout controls (Phase 20-A, ``REV/20`` #1, #2): which Reasoning V3 capabilities this deployment runs and shows.

Repository-side application controls only. This module decides capability selection from configuration. It deploys nothing,
changes no topology and touches no security setting. Who can reach the reasoning surface is still the authenticating proxy and
the manager allow-list (``ATLAS_REASONING_MANAGERS``); those, CSRF, Origin, content-type and CSP checks are unchanged and apply to
every capability this module turns on.

The flags (validated together; an invalid combination is a configuration error, never a silent correction):

==================================  ==========  ===================================================================================
``ATLAS_REASONING_V3``              off         master switch (Phase 01). Off: every capability below is off, whatever it says.
``ATLAS_REASONING_EXECUTION``       on          Reasoning V3 processing may run (Change Gate, reasoning, executive synthesis). The
                                                kill switch for model work. Off never hides or deletes stored results.
``ATLAS_REASONING_AUDIENCE``        none        who the reasoning surface is presented to: ``none`` (nothing is served: shadow),
                                                ``internal`` (internal review), ``management`` (management beta, or primary).
``ATLAS_REASONING_CARDS_PRIMARY``   off         reasoning-first cards are the primary management card experience (needs management).
``ATLAS_REASONING_HUMAN_CONTEXT``   off         manager notes, Atlas Question answers and Teach Atlas interactions (needs an audience).
``ATLAS_REASONING_EXECUTIVE_HOME``  off         the ExecutiveBrief leads the reasoning home (needs management).
==================================  ==========  ===================================================================================

Every user-visible capability defaults **off**, so ``ATLAS_REASONING_V3=on`` alone is the shadow stage. The six REV/20 stages are
named flag sets (``STAGES``); ``stage_of`` reports which one a configuration is (or ``custom``). Moving between stages is changing these
variables and restarting the processes; nothing here deletes or rewrites canonical state, so every move is reversible.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from atlas_reasoning import settings
from atlas_reasoning.settings import ReasoningConfigError

ROLLOUT_VERSION = "reasoning-rollout-v1"
EXECUTION_ENV = "ATLAS_REASONING_EXECUTION"
AUDIENCE_ENV = "ATLAS_REASONING_AUDIENCE"
CARDS_PRIMARY_ENV = "ATLAS_REASONING_CARDS_PRIMARY"
HUMAN_CONTEXT_ENV = "ATLAS_REASONING_HUMAN_CONTEXT"
EXECUTIVE_HOME_ENV = "ATLAS_REASONING_EXECUTIVE_HOME"
ROLLOUT_ENVS = (settings.FLAG_ENV, EXECUTION_ENV, AUDIENCE_ENV, CARDS_PRIMARY_ENV, HUMAN_CONTEXT_ENV, EXECUTIVE_HOME_ENV)


class RolloutError(ReasoningConfigError):
    """An invalid rollout configuration. The message names variables and allowed values only, never a secret."""


class ExecutionDisabled(settings.ReasoningDisabled):
    """Reasoning V3 processing was requested while ``ATLAS_REASONING_EXECUTION`` (or the master switch) is off."""


class Audience(StrEnum):
    NONE = "none"
    INTERNAL = "internal"
    MANAGEMENT = "management"


class Surface(StrEnum):
    """The primary management experience the configuration asks for (the operator's routing follows it; this module routes nothing)."""

    DETERMINISTIC_DASHBOARD = "deterministic_dashboard"
    REASONING_CARDS = "reasoning_cards"
    EXECUTIVE_BRIEF = "executive_brief"


@dataclass(frozen=True)
class RolloutConfig:
    """A validated rollout configuration. ``enabled`` is the master switch; every property is the *effective* capability."""

    enabled: bool = False
    execution_flag: bool = True
    audience_flag: Audience = Audience.NONE
    cards_primary_flag: bool = False
    human_context_flag: bool = False
    executive_home_flag: bool = False

    def __post_init__(self) -> None:
        problems = dependency_errors(self.audience_flag, self.cards_primary_flag, self.human_context_flag, self.executive_home_flag)
        if problems:
            raise RolloutError("invalid Reasoning V3 rollout: " + "; ".join(problems))

    @staticmethod
    def full() -> RolloutConfig:
        """Every capability on: the Phase 16/17 composition (stage 6)."""
        return RolloutConfig(True, True, Audience.MANAGEMENT, True, True, True)

    # --- effective capabilities ---------------------------------------------------------------------------------------------

    @property
    def execution(self) -> bool:
        return self.enabled and self.execution_flag

    @property
    def audience(self) -> Audience:
        return self.audience_flag if self.enabled else Audience.NONE

    @property
    def reasoning_visible(self) -> bool:
        return self.audience != Audience.NONE

    @property
    def internal_review(self) -> bool:
        return self.audience == Audience.INTERNAL

    @property
    def management_beta(self) -> bool:
        return self.audience == Audience.MANAGEMENT and not self.cards_primary

    @property
    def cards_primary(self) -> bool:
        return self.enabled and self.cards_primary_flag

    @property
    def human_context(self) -> bool:
        return self.enabled and self.human_context_flag

    @property
    def executive_home(self) -> bool:
        return self.enabled and self.executive_home_flag

    @property
    def primary_surface(self) -> Surface:
        if self.executive_home and self.cards_primary:
            return Surface.EXECUTIVE_BRIEF
        return Surface.REASONING_CARDS if self.cards_primary else Surface.DETERMINISTIC_DASHBOARD

    @property
    def stage(self) -> str:
        return stage_of(self)

    def to_dict(self) -> dict[str, Any]:
        """Content-free, deterministic: the effective capabilities, the stage they form and the configured flags."""
        return {"version": ROLLOUT_VERSION, "stage": self.stage, "enabled": self.enabled, "execution": self.execution,
                "audience": self.audience.value, "reasoning_visible": self.reasoning_visible, "internal_review": self.internal_review,
                "management_beta": self.management_beta, "cards_primary": self.cards_primary, "human_context": self.human_context,
                "executive_home": self.executive_home, "primary_surface": self.primary_surface.value,
                "configured": {"execution": self.execution_flag, "audience": self.audience_flag.value, "cards_primary": self.cards_primary_flag,
                               "human_context": self.human_context_flag, "executive_home": self.executive_home_flag}}


def dependency_errors(audience: Audience, cards_primary: bool, human_context: bool, executive_home: bool) -> list[str]:
    """The genuine dependencies between capabilities (checked on the configured flags, master switch aside)."""
    problems = []
    if cards_primary and audience != Audience.MANAGEMENT:
        problems.append(f"{CARDS_PRIMARY_ENV}=on needs {AUDIENCE_ENV}=management (primary for management, not {audience.value})")
    if executive_home and audience != Audience.MANAGEMENT:
        problems.append(f"{EXECUTIVE_HOME_ENV}=on needs {AUDIENCE_ENV}=management (an executive home nobody is shown is a contradiction)")
    if human_context and audience == Audience.NONE:
        problems.append(f"{HUMAN_CONTEXT_ENV}=on needs a reasoning surface ({AUDIENCE_ENV}=internal or management)")
    return problems


def rollout_config(env: Mapping[str, str] | None = None) -> RolloutConfig:
    """The validated configuration from the environment. Unknown values and invalid combinations raise ``RolloutError``."""
    env = os.environ if env is None else env
    try:
        enabled = settings.flag(env, settings.FLAG_ENV)
        execution = settings.flag(env, EXECUTION_ENV, default=True)
        cards, human, executive = (settings.flag(env, name) for name in (CARDS_PRIMARY_ENV, HUMAN_CONTEXT_ENV, EXECUTIVE_HOME_ENV))
    except ReasoningConfigError as error:
        raise RolloutError(str(error)) from None
    raw = (env.get(AUDIENCE_ENV) or "").strip().lower() or Audience.NONE.value
    try:
        audience = Audience(raw)
    except ValueError:
        raise RolloutError(f"{AUDIENCE_ENV} must be one of {', '.join(a.value for a in Audience)}") from None
    return RolloutConfig(enabled, execution, audience, cards, human, executive)


def require_execution(env: Mapping[str, str] | None = None) -> RolloutConfig:
    """For every command that runs Reasoning V3 processing: the master switch (``ReasoningDisabled``), then the execution flag."""
    settings.require_enabled(env)
    config = rollout_config(env)
    if not config.execution:
        raise ExecutionDisabled(f"Reasoning V3 processing is disabled ({EXECUTION_ENV}=off); stored results stay readable")
    return config


# --- the REV/20 stages ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    number: int
    name: str
    description: str
    env: Mapping[str, str]

    def config(self) -> RolloutConfig:
        return rollout_config(self.env)


def _stage_env(enabled: bool, audience: str = "none", cards: bool = False, human: bool = False, executive: bool = False) -> dict[str, str]:
    on = {True: "on", False: "off"}
    return {settings.FLAG_ENV: on[enabled], EXECUTION_ENV: "on", AUDIENCE_ENV: audience, CARDS_PRIMARY_ENV: on[cards],
            HUMAN_CONTEXT_ENV: on[human], EXECUTIVE_HOME_ENV: on[executive]}


STAGES: tuple[Stage, ...] = (
    Stage(0, "off", "Reasoning V3 off: deterministic Atlas only (today's production)", _stage_env(False)),
    Stage(1, "shadow", "reasoning runs and persists; nothing is user-visible", _stage_env(True)),
    Stage(2, "internal_review", "the reasoning surface for internal reviewers, marked as internal review", _stage_env(True, "internal")),
    Stage(3, "management_beta", "reasoning cards for management as a beta; the deterministic dashboard stays primary",
          _stage_env(True, "management")),
    Stage(4, "cards_primary", "reasoning-first cards are the primary management card experience", _stage_env(True, "management", True)),
    Stage(5, "human_context", "manager notes, answers and Teach Atlas enabled", _stage_env(True, "management", True, True)),
    Stage(6, "executive_home", "the ExecutiveBrief leads the reasoning home", _stage_env(True, "management", True, True, True)),
)


def _signature(config: RolloutConfig) -> tuple[Any, ...]:
    return (config.enabled, config.execution, config.audience, config.cards_primary, config.human_context, config.executive_home)


def stage_of(config: RolloutConfig) -> str:
    """The REV/20 stage this configuration is, by its effective capabilities; ``custom`` for any other valid combination (for
    example a stage with ``ATLAS_REASONING_EXECUTION=off`` during an incident). Master off is always ``off``."""
    if not config.enabled:
        return "off"
    wanted = _signature(config)
    return next((stage.name for stage in STAGES if _signature(stage.config()) == wanted), "custom")


def stage(name: str) -> Stage:
    try:
        return next(stage for stage in STAGES if stage.name == name)
    except StopIteration:
        raise RolloutError(f"unknown stage {name!r}; stages: {', '.join(s.name for s in STAGES)}") from None
