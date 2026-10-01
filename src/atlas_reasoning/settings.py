"""Reasoning V3 configuration, read only from the environment (never from a committed file).

========================================  ========  ==============================================
Variable                                  Default   Meaning
========================================  ========  ==============================================
ATLAS_REASONING_V3                        off       Feature flag. ``on`` enables Reasoning V3 runs; anything but
                                                    on/off (1/0, true/false, yes/no) is a configuration error.
========================================  ========  ==============================================

With the flag off (the default) nothing in Atlas calls Reasoning V3: the site build, sync, publication and every existing
document are exactly what they were before this package existed. Commands that only prepare infrastructure (database
migrations and health checks) work with the flag off, so a database can be migrated before reasoning writes are enabled
(``REV/20``, rollout step 3). Commands that run reasoning refuse to start while the flag is off.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

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
