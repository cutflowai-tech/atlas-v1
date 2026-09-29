"""Typed, validated deployment configuration for the Atlas production sync.

Only deployment-specific values live here, read from environment variables. Business mappings,
the Monday board and its column definitions stay in the versioned Monday contract
(``config/monday-contract-v*.json``); this module only chooses which approved contract version is
active, and can assert that the deployment points at that contract's board.

Environment variables (see ``.env.example``):

========================================  ========  ==============================================
Variable                                  Required  Meaning
========================================  ========  ==============================================
MONDAY_API_TOKEN / MONDAY_API_TOKEN_FILE  for sync  Read-only Monday API token, or a file holding it
                                                    (e.g. a Docker secret). Set one, never both.
MONDAY_API_VERSION                        no        Monday API version header (default 2025-04).
ATLAS_CONTRACT_VERSION                    no        Monday contract; production accepts only 1.4.0 (default).
ATLAS_MONDAY_BOARD_ID                     no        If set, must equal the contract's board ID.
ATLAS_DATA_DIR                            *         Base directory; derives the three below.
ATLAS_RAW_DIR                             *         Immutable raw Monday evidence (default DATA/raw/monday).
ATLAS_BUILD_DIR                           *         Generated builds (default DATA/builds).
ATLAS_PUBLISH_DIR                         *         Published output (default DATA/published).
ATLAS_LOCK_DIR                            **        Holds the production-operation lock file (default DATA/locks).
ATLAS_HISTORY_START                       no        UTC start of the activity-log history
                                                    (default 2026-02-01T00:00:00Z).
ATLAS_SYNC_INTERVAL_SECONDS               no        Seconds between syncs (default 3600).
ATLAS_STALE_AFTER_SECONDS                 no        Data older than this is stale (default 7200).
ATLAS_MAX_CONSECUTIVE_FAILURES            no        Failed syncs in a row before it is a failure
                                                    state (default 3).
ATLAS_SYNC_MAX_DURATION_SECONDS           no        Time budget for one sync attempt; no new stage
                                                    or Monday request starts after it (default 7200).
========================================  ========  ==============================================

``*`` Either ATLAS_DATA_DIR, or all three of ATLAS_RAW_DIR, ATLAS_BUILD_DIR and ATLAS_PUBLISH_DIR.
``**`` Needed by run-once, publish and rollback: derived from ATLAS_DATA_DIR, or set explicitly (and then, with
ATLAS_DATA_DIR, it must be inside it). It must not overlap the raw, build or publish directories.

The token is held in a :class:`Secret`, which never renders its value in ``repr``/``str``, cannot be
serialised to JSON, and is only released by :meth:`Secret.reveal` when a Monday client is built.
Configuration errors never contain the token.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import IngestError, parse_utc_timestamp
from atlas_commander.runtime import ACTIVE_CONTRACT_VERSION, CONTRACT_PATHS, load_contract_version
from atlas_monday_probe.client import (
    API_VERSION_ENV,
    DEFAULT_API_VERSION,
    TOKEN_ENV,
    TOKEN_FILE_ENV,
    InvalidMondaySetting,
    MissingAccess,
    ReadOnlyMondayClient,
    token_from_environment,
    validate_api_version,
)
from atlas_monday_probe.raw_store import inside_git_worktree

CONTRACT_VERSION_ENV = "ATLAS_CONTRACT_VERSION"
BOARD_ID_ENV = "ATLAS_MONDAY_BOARD_ID"
DATA_DIR_ENV = "ATLAS_DATA_DIR"
RAW_DIR_ENV = "ATLAS_RAW_DIR"
BUILD_DIR_ENV = "ATLAS_BUILD_DIR"
PUBLISH_DIR_ENV = "ATLAS_PUBLISH_DIR"
LOCK_DIR_ENV = "ATLAS_LOCK_DIR"
HISTORY_START_ENV = "ATLAS_HISTORY_START"
INTERVAL_ENV = "ATLAS_SYNC_INTERVAL_SECONDS"
STALE_ENV = "ATLAS_STALE_AFTER_SECONDS"
FAILURES_ENV = "ATLAS_MAX_CONSECUTIVE_FAILURES"
MAX_DURATION_ENV = "ATLAS_SYNC_MAX_DURATION_SECONDS"
RETENTION_ENV = "ATLAS_RETENTION_SECONDS"

# Production sync runs only the contract validated live (REAL-004). Older contracts stay loadable for
# reproducing historical results and fixtures, but never for production sync.
PRODUCTION_CONTRACT_VERSIONS = ("1.4.0",)
# The history start used by every validated live run (REAL-003, REAL-004).
DEFAULT_HISTORY_START = "2026-02-01T00:00:00Z"
DEFAULT_INTERVAL_SECONDS = 3600
DEFAULT_STALE_AFTER_SECONDS = 7200
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_MAX_DURATION_SECONDS = 7200
DEFAULT_RETENTION_SECONDS = 96 * 60 * 60
MIN_MAX_DURATION_SECONDS = 60
MIN_INTERVAL_SECONDS = 300
MAX_INTERVAL_SECONDS = 86_400
REDACTED = "<redacted>"


class ConfigError(ValueError):
    """Invalid or missing deployment configuration. Lists every problem; never contains the token."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("invalid Atlas sync configuration:\n- " + "\n- ".join(self.problems))


class Secret:
    """A secret string that is never rendered, logged or serialised by accident."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return REDACTED

    __str__ = __repr__

    def __format__(self, spec: str) -> str:
        return REDACTED

    def __reduce__(self) -> Any:
        raise TypeError("a Secret cannot be pickled")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(("Secret", self._value))


@dataclass(frozen=True)
class SyncConfig:
    monday_token: Secret | None
    monday_token_source: str | None
    monday_api_version: str
    contract_version: str
    board_id: str
    raw_dir: Path
    build_dir: Path
    publish_dir: Path
    history_start: str
    sync_interval_seconds: int
    stale_after_seconds: int
    max_consecutive_failures: int
    max_sync_duration_seconds: int = DEFAULT_MAX_DURATION_SECONDS
    retention_seconds: int = DEFAULT_RETENTION_SECONDS
    # Directory of the production-operation lock (see atlas_sync.lock); None when neither ATLAS_DATA_DIR nor ATLAS_LOCK_DIR is set.
    lock_dir: Path | None = None

    def require_monday_token(self) -> Secret:
        """The token, or MissingAccess (fail closed) when a Monday operation needs one and none is configured."""
        if self.monday_token is None:
            raise MissingAccess(f"{TOKEN_ENV} or {TOKEN_FILE_ENV} is required for Monday access; neither is set")
        return self.monday_token

    def monday_client(self) -> ReadOnlyMondayClient:
        """A read-only Monday client using this configuration's token and API version."""
        return ReadOnlyMondayClient.from_token(self.require_monday_token().reveal(), self.monday_api_version)

    def contract(self) -> dict[str, Any]:
        return load_contract_version(self.contract_version)

    def redacted(self) -> dict[str, Any]:
        """A JSON-safe, loggable view: the token appears only as whether and where it is configured."""
        return {
            "monday_token": REDACTED if self.monday_token is not None else None,
            "monday_token_source": self.monday_token_source,
            "monday_api_version": self.monday_api_version,
            "contract_version": self.contract_version,
            "board_id": self.board_id,
            "raw_dir": str(self.raw_dir),
            "build_dir": str(self.build_dir),
            "publish_dir": str(self.publish_dir),
            "history_start": self.history_start,
            "sync_interval_seconds": self.sync_interval_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "max_consecutive_failures": self.max_consecutive_failures,
            "max_sync_duration_seconds": self.max_sync_duration_seconds,
            "retention_seconds": self.retention_seconds,
            "lock_dir": str(self.lock_dir) if self.lock_dir is not None else None,
        }


def _int(env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int | None, problems: list[str]) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        problems.append(f"{name} must be a whole number, got {raw!r}")
        return default
    if value < minimum or (maximum is not None and value > maximum):
        problems.append(f"{name} must be between {minimum} and {maximum if maximum is not None else 'any'}, got {value}")
    return value


def _directory(env: Mapping[str, str], name: str, base: Path | None, default_suffix: str, problems: list[str]) -> Path | None:
    raw = env.get(name, "").strip()
    if not raw:
        if base is None:
            problems.append(f"{name} is required (or set {DATA_DIR_ENV})")
            return None
        return base / default_suffix
    path = Path(raw).expanduser()
    if not path.is_absolute():
        problems.append(f"{name} must be an absolute path, got {raw!r}")
        return None
    return path


def _check_directories(dirs: dict[str, Path], problems: list[str]) -> None:
    resolved = {}
    for name, path in dirs.items():
        if path.exists() and not path.is_dir():
            problems.append(f"{name} exists and is not a directory: {path}")
        if inside_git_worktree(path.resolve()):
            problems.append(f"{name} must be outside any Git checkout (it holds real Monday data): {path}")
        resolved[name] = path.resolve()
    names = list(resolved)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            a, b = resolved[first], resolved[second]
            if a == b or a in b.parents or b in a.parents:
                problems.append(f"{first} and {second} must be separate, non-nested directories: {a}, {b}")


def load_sync_config(environ: Mapping[str, str] | None = None, *, require_token: bool = False,
                     now: datetime | None = None) -> SyncConfig:
    """Read and validate the deployment configuration from ``environ`` (default: the process environment).

    With ``require_token=True`` a missing token is a configuration error; otherwise it is allowed here
    and :meth:`SyncConfig.require_monday_token` fails closed when Monday access is actually needed."""
    env = dict(os.environ) if environ is None else dict(environ)
    problems: list[str] = []

    token: Secret | None = None
    source: str | None = None
    try:
        token = Secret(token_from_environment(env))
        source = TOKEN_FILE_ENV if env.get(TOKEN_FILE_ENV) else TOKEN_ENV
    except MissingAccess as error:
        if require_token or env.get(TOKEN_FILE_ENV):
            problems.append(str(error))
    except InvalidMondaySetting as error:
        problems.append(str(error))

    api_version = env.get(API_VERSION_ENV, "").strip() or DEFAULT_API_VERSION
    try:
        validate_api_version(api_version)
    except InvalidMondaySetting as error:
        problems.append(str(error))

    contract_version = env.get(CONTRACT_VERSION_ENV, "").strip() or ACTIVE_CONTRACT_VERSION
    board_id = ""
    if contract_version not in CONTRACT_PATHS:
        problems.append(f"{CONTRACT_VERSION_ENV} {contract_version!r} is not an approved contract version ({', '.join(sorted(CONTRACT_PATHS))})")
    elif contract_version not in PRODUCTION_CONTRACT_VERSIONS:
        problems.append(f"{CONTRACT_VERSION_ENV} {contract_version!r} is not allowed for production sync; "
                        f"only {', '.join(PRODUCTION_CONTRACT_VERSIONS)} is (older contracts are kept for reproducing history only)")
    else:
        board_id = str(load_contract_version(contract_version)["source_board"]["board_id"])
        expected = env.get(BOARD_ID_ENV, "").strip()
        if expected and expected != board_id:
            problems.append(f"{BOARD_ID_ENV} {expected!r} does not match board {board_id} in contract {contract_version}; "
                            "the board is defined by the contract")

    base_raw = env.get(DATA_DIR_ENV, "").strip()
    base: Path | None = None
    if base_raw:
        base = Path(base_raw).expanduser()
        if not base.is_absolute():
            problems.append(f"{DATA_DIR_ENV} must be an absolute path, got {base_raw!r}")
            base = None
    raw_dir = _directory(env, RAW_DIR_ENV, base, "raw/monday", problems)
    build_dir = _directory(env, BUILD_DIR_ENV, base, "builds", problems)
    publish_dir = _directory(env, PUBLISH_DIR_ENV, base, "published", problems)
    lock_dir: Path | None = None
    if env.get(LOCK_DIR_ENV, "").strip() or base is not None:
        lock_dir = _directory(env, LOCK_DIR_ENV, base, "locks", problems)
        if lock_dir is not None and base is not None and base.resolve() not in lock_dir.resolve().parents:
            problems.append(f"{LOCK_DIR_ENV} must be inside {DATA_DIR_ENV} ({base}), got {lock_dir}")
    if raw_dir and build_dir and publish_dir:
        dirs = {RAW_DIR_ENV: raw_dir, BUILD_DIR_ENV: build_dir, PUBLISH_DIR_ENV: publish_dir}
        _check_directories({**dirs, LOCK_DIR_ENV: lock_dir} if lock_dir is not None else dirs, problems)

    history_start = env.get(HISTORY_START_ENV, "").strip() or DEFAULT_HISTORY_START
    try:
        if parse_utc_timestamp(history_start) >= (now or datetime.now(timezone.utc)):
            problems.append(f"{HISTORY_START_ENV} must be in the past, got {history_start}")
    except IngestError:
        problems.append(f"{HISTORY_START_ENV} must be UTC like 2026-02-01T00:00:00Z, got {history_start!r}")

    interval = _int(env, INTERVAL_ENV, DEFAULT_INTERVAL_SECONDS, MIN_INTERVAL_SECONDS, MAX_INTERVAL_SECONDS, problems)
    stale = _int(env, STALE_ENV, DEFAULT_STALE_AFTER_SECONDS, MIN_INTERVAL_SECONDS, None, problems)
    failures = _int(env, FAILURES_ENV, DEFAULT_MAX_CONSECUTIVE_FAILURES, 1, 100, problems)
    max_duration = _int(env, MAX_DURATION_ENV, DEFAULT_MAX_DURATION_SECONDS, MIN_MAX_DURATION_SECONDS, MAX_INTERVAL_SECONDS, problems)
    retention = _int(env, RETENTION_ENV, DEFAULT_RETENTION_SECONDS, 3600, None, problems)
    if stale <= interval:
        problems.append(f"{STALE_ENV} ({stale}) must be greater than {INTERVAL_ENV} ({interval})")

    if problems or raw_dir is None or build_dir is None or publish_dir is None:
        raise ConfigError(problems or ["data directories are not configured"])
    return SyncConfig(monday_token=token, monday_token_source=source, monday_api_version=api_version, contract_version=contract_version,
                      board_id=board_id, raw_dir=raw_dir, build_dir=build_dir, publish_dir=publish_dir, history_start=history_start,
                      sync_interval_seconds=interval, stale_after_seconds=stale, max_consecutive_failures=failures,
                      max_sync_duration_seconds=max_duration, retention_seconds=retention, lock_dir=lock_dir)
