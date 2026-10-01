"""Reasoning V3 configuration, read only from the environment (never from a committed file).

========================================  ========  ==============================================
Variable                                  Default   Meaning
========================================  ========  ==============================================
ATLAS_REASONING_V3                        off       Feature flag. ``on`` enables Reasoning V3 runs; anything but
                                                    on/off (1/0, true/false, yes/no) is a configuration error.
ATLAS_REASONING_DATABASE_URL              *         PostgreSQL URL of the canonical Reasoning V3 state.
ATLAS_REASONING_DATABASE_URL_FILE         *         A file holding that URL (e.g. a Docker secret). Set one, never both.
========================================  ========  ==============================================

``*`` Required only by commands that use the database (migrate, db-health, gate, debug lookups).

With the flag off (the default) nothing in Atlas calls Reasoning V3: the site build, sync, publication and every existing
document are exactly what they were before this package existed. Commands that only prepare infrastructure (database
migrations and health checks) work with the flag off, so a database can be migrated before reasoning writes are enabled
(``REV/20``, rollout step 3). Commands that run reasoning refuse to start while the flag is off.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
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
