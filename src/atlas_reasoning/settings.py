"""Reasoning V3 configuration, read only from the environment (never from a committed file).

========================================  ========  ==============================================
Variable                                  Default   Meaning
========================================  ========  ==============================================
ATLAS_REASONING_V3                        off       Feature flag. ``on`` enables Reasoning V3 runs; anything but
                                                    on/off (1/0, true/false, yes/no) is a configuration error.
ATLAS_REASONING_DATABASE_URL              *         PostgreSQL URL of the canonical Reasoning V3 state.
ATLAS_REASONING_DATABASE_URL_FILE         *         A file holding that URL (e.g. a Docker secret). Set one, never both.
OPENROUTER_API_KEY                        **        OpenRouter API key.
OPENROUTER_API_KEY_FILE                   **        A file holding the key. Set one, never both.
ATLAS_REASONING_MODEL                     pinned    Must equal the pinned production model (openai/gpt-5.6-sol) unless
ATLAS_REASONING_ALLOW_MODEL_OVERRIDE      off       is on (evaluation and rollback only).
ATLAS_REASONING_OPENROUTER_BASE_URL       https://openrouter.ai/api/v1
ATLAS_REASONING_LLM_TIMEOUT_SECONDS       120       Per attempt (5-600).
ATLAS_REASONING_LLM_MAX_RETRIES           3         Retries after the first attempt (0-6).
ATLAS_REASONING_LLM_BACKOFF_SECONDS       2         First backoff; doubles per retry (0-60).
ATLAS_REASONING_LLM_MAX_BACKOFF_SECONDS   60        Longest single wait, including Retry-After (0-600).
ATLAS_REASONING_LLM_CONCURRENCY           4         Provider requests in flight at once (1-32).
========================================  ========  ==============================================

``*`` Required only by commands that use the database (migrate, db-health, gate, debug lookups).
``**`` Required only for live provider calls (provider-health without --dry-run, later reasoning phases). Tests never need it.

With the flag off (the default) nothing in Atlas calls Reasoning V3: the site build, sync, publication and every existing
document are exactly what they were before this package existed. Commands that only prepare infrastructure (database
migrations and health checks) work with the flag off, so a database can be migrated before reasoning writes are enabled
(``REV/20``, rollout step 3). Commands that run reasoning refuse to start while the flag is off.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

FLAG_ENV = "ATLAS_REASONING_V3"
_ON = frozenset({"1", "on", "true", "yes"})
_OFF = frozenset({"", "0", "off", "false", "no"})


class ReasoningConfigError(ValueError):
    """Reasoning V3 configuration is missing or invalid. Messages never contain secret values."""


class ReasoningDisabled(RuntimeError):
    """A reasoning run was requested while the Reasoning V3 feature flag is off."""


def flag(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _ON:
        return True
    if value in _OFF:
        return False
    raise ReasoningConfigError(f"{name} must be on or off, not {raw!r}")


def reasoning_enabled(env: Mapping[str, str] | None = None) -> bool:
    """The Reasoning V3 feature flag. Default OFF."""
    return flag(os.environ if env is None else env, FLAG_ENV)


def require_enabled(env: Mapping[str, str] | None = None) -> None:
    if not reasoning_enabled(env):
        raise ReasoningDisabled(f"Reasoning V3 is disabled; set {FLAG_ENV}=on to run it")


DATABASE_URL_ENV = "ATLAS_REASONING_DATABASE_URL"
DATABASE_URL_FILE_ENV = "ATLAS_REASONING_DATABASE_URL_FILE"


def secret_value(env: Mapping[str, str], name: str, file_name: str, *, required: bool = True) -> str | None:
    """A secret from ``name`` or from the file named by ``file_name`` (exactly one). Errors name the variable, never the value."""
    direct, path = env.get(name, "").strip(), env.get(file_name, "").strip()
    if direct and path:
        raise ReasoningConfigError(f"set {name} or {file_name}, not both")
    if path:
        try:
            direct = Path(path).read_text().strip()
        except OSError as error:
            raise ReasoningConfigError(f"{file_name} cannot be read ({error.strerror})") from None
        if not direct:
            raise ReasoningConfigError(f"{file_name} names an empty file")
    if not direct:
        if required:
            raise ReasoningConfigError(f"{name} (or {file_name}) is not set")
        return None
    return direct


def database_url(env: Mapping[str, str] | None = None) -> str:
    url = secret_value(os.environ if env is None else env, DATABASE_URL_ENV, DATABASE_URL_FILE_ENV)
    assert url is not None
    if not url.startswith(("postgresql://", "postgres://")):
        raise ReasoningConfigError(f"{DATABASE_URL_ENV} must be a postgresql:// URL")
    return url


OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
OPENROUTER_KEY_FILE_ENV = "OPENROUTER_API_KEY_FILE"
MODEL_ENV = "ATLAS_REASONING_MODEL"
MODEL_OVERRIDE_ENV = "ATLAS_REASONING_ALLOW_MODEL_OVERRIDE"
BASE_URL_ENV = "ATLAS_REASONING_OPENROUTER_BASE_URL"
# The production reasoning model: GPT-5.6 Sol through OpenRouter (slug verified against OpenRouter's model list on 2026-10-01;
# it supports structured outputs).
PINNED_MODEL = "openai/gpt-5.6-sol"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def _number(env: Mapping[str, str], name: str, default: float, low: float, high: float, *, integer: bool = False) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw) if integer else float(raw)
    except ValueError:
        raise ReasoningConfigError(f"{name} must be a number, not {raw!r}") from None
    if not low <= value <= high:
        raise ReasoningConfigError(f"{name} must be between {low:g} and {high:g}")
    return value


@dataclass(frozen=True)
class GatewaySettings:
    """Provider gateway limits. Defaults are conservative; every value is bounded."""

    model: str = PINNED_MODEL
    timeout_seconds: float = 120.0
    max_retries: int = 3
    backoff_seconds: float = 2.0
    max_backoff_seconds: float = 60.0
    concurrency: int = 4


@dataclass(frozen=True)
class OpenRouterSettings:
    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL

    def __post_init__(self) -> None:
        if not self.base_url.startswith("https://") and not self.base_url.startswith("http://127.0.0.1"):
            raise ReasoningConfigError(f"{BASE_URL_ENV} must be an https:// URL")


def gateway_settings(env: Mapping[str, str] | None = None) -> GatewaySettings:
    env = os.environ if env is None else env
    model = env.get(MODEL_ENV, "").strip() or PINNED_MODEL
    if model != PINNED_MODEL and not flag(env, MODEL_OVERRIDE_ENV):
        raise ReasoningConfigError(f"{MODEL_ENV} must be the pinned model {PINNED_MODEL} (set {MODEL_OVERRIDE_ENV}=on to override)")
    return GatewaySettings(
        model=model,
        timeout_seconds=_number(env, "ATLAS_REASONING_LLM_TIMEOUT_SECONDS", 120.0, 5, 600),
        max_retries=int(_number(env, "ATLAS_REASONING_LLM_MAX_RETRIES", 3, 0, 6, integer=True)),
        backoff_seconds=_number(env, "ATLAS_REASONING_LLM_BACKOFF_SECONDS", 2.0, 0, 60),
        max_backoff_seconds=_number(env, "ATLAS_REASONING_LLM_MAX_BACKOFF_SECONDS", 60.0, 0, 600),
        concurrency=int(_number(env, "ATLAS_REASONING_LLM_CONCURRENCY", 4, 1, 32, integer=True)),
    )


def openrouter_settings(env: Mapping[str, str] | None = None) -> OpenRouterSettings:
    env = os.environ if env is None else env
    key = secret_value(env, OPENROUTER_KEY_ENV, OPENROUTER_KEY_FILE_ENV)
    assert key is not None
    return OpenRouterSettings(api_key=key, base_url=(env.get(BASE_URL_ENV, "").strip() or DEFAULT_BASE_URL).rstrip("/"))
