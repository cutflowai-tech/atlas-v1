"""The single cross-process lock for Atlas production operations (run-once, publish, rollback, scheduled-run).

Ownership comes only from an OS advisory lock (``flock``) on ``<ATLAS_LOCK_DIR>/production.lock``
(default ``<ATLAS_DATA_DIR>/locks/production.lock``). The file itself may stay on disk forever: its existence
proves nothing. The kernel releases the lock when the holder's file descriptor closes, including when the
process exits, raises, is interrupted, crashes or is killed, so a stale lock never needs manual deletion.

Acquisition is non-blocking: if another process holds the lock, :class:`OperationLocked` is raised at once
and the caller does nothing else. There is no queue and no waiting.

While held, the file contains safe diagnostic metadata (operation, PID, host, time, target). A process
that fails to acquire the lock may read it to say who appears to hold it; it is never used to decide
whether the lock is held.

Ownership layer: the public entry points :func:`atlas_sync.run.run_once`, :func:`atlas_sync.publish.publish`
and :func:`atlas_sync.publish.rollback` each take this lock once for their whole operation. The CLI only
calls those entry points and never takes the lock itself. The lock is deliberately not re-entrant: taking it
again in the same process (a programming error) fails fast with :class:`OperationLocked` instead of hanging.
The scheduled-cycle entry point owns one lock across its private already-locked run and publish helpers.
"""

from __future__ import annotations

import fcntl
import json
import os
import socket
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_commander.ingest import RUN_ID_PATTERN, Clock, utc_now
from atlas_monday_probe.raw_store import inside_git_worktree

from .config import SyncConfig

LOCK_FILE_NAME = "production.lock"
LOCK_VERSION = "atlas-lock-v1"
OPERATIONS = ("run-once", "publish", "rollback", "scheduled-run")
# One exit code for lock contention across every production operation (EX_TEMPFAIL: try again later).
EXIT_LOCKED = 75
LOCKED_CATEGORY = "operation_locked"
_METADATA_KEYS: dict[str, Any] = {"lock_version": str, "operation": str, "pid": int, "hostname": str, "acquired_at": str, "target": (str, type(None))}
_MAX_METADATA_BYTES = 4096


class LockError(Exception):
    """The lock location is missing or unsafe; nothing was started."""

    failure_category = "lock_configuration"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OperationLocked(Exception):
    """Another Atlas production operation holds the lock; nothing was started."""

    failure_category = LOCKED_CATEGORY

    def __init__(self, requested_operation: str, holder: dict[str, Any] | None, at: str) -> None:
        super().__init__(f"another Atlas production operation is running; {requested_operation} was not started")
        self.requested_operation, self.holder, self.at = requested_operation, holder, at

    def as_dict(self) -> dict[str, Any]:
        """The safe structured result for a request that never acquired the lock."""
        return {"status": "locked", "category": LOCKED_CATEGORY, "requested_operation": self.requested_operation,
                "holder": self.holder, "at": self.at}


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_target(value: str | None) -> str | None:
    """Only a run-style ID is recorded as the target; anything else a caller passed is not echoed."""
    if value is None:
        return None
    return value if RUN_ID_PATTERN.match(value) else "invalid"


def lock_path(config: SyncConfig) -> Path:
    if config.lock_dir is None:
        raise LockError("no lock directory is configured; set ATLAS_DATA_DIR or ATLAS_LOCK_DIR")
    return config.lock_dir.expanduser() / LOCK_FILE_NAME


def _open_lock_file(config: SyncConfig) -> int:
    """Open (creating if needed) the lock file without following symlinks; fail closed on anything unsafe."""
    path = lock_path(config)
    directory = path.parent
    if not directory.is_absolute():
        raise LockError("the lock directory must be an absolute path")
    if directory.is_symlink():
        raise LockError("the lock directory is a symlink; it must be a real directory")
    if inside_git_worktree(directory.resolve()):
        raise LockError("the lock directory must be outside any Git checkout")
    resolved = directory.resolve()
    for root in (config.raw_dir, config.build_dir, config.publish_dir):
        other = root.expanduser().resolve()
        if resolved == other or other in resolved.parents or resolved in other.parents:
            raise LockError("the lock directory overlaps the raw, build or publish directory")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir():
        raise LockError("the lock directory is not a real directory")
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        raise LockError("the lock directory cannot be opened safely") from None
    try:
        fd = os.open(LOCK_FILE_NAME, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory_fd)
    except OSError:   # ELOOP for a symlink, EISDIR, permissions, ...
        raise LockError("the lock file cannot be opened safely (it must be a regular file, not a symlink)") from None
    finally:
        os.close(directory_fd)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
        os.close(fd)
        raise LockError("the lock file must be a regular, unlinked-elsewhere file owned by this user")
    return fd


def _read_holder(fd: int) -> dict[str, Any] | None:
    """Best-effort, diagnostic-only view of the holder's metadata; only known, well-typed fields are returned."""
    try:
        document = json.loads(os.pread(fd, _MAX_METADATA_BYTES, 0))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    holder = {key: document[key] for key, kind in _METADATA_KEYS.items() if key in document and isinstance(document[key], kind)}
    if isinstance(holder.get("target"), str):
        holder["target"] = safe_target(holder["target"])
    return holder or None


def _write_metadata(fd: int, metadata: dict[str, Any]) -> None:
    data = json.dumps(metadata, sort_keys=True).encode() + b"\n"
    os.ftruncate(fd, 0)
    os.pwrite(fd, data, 0)
    os.fsync(fd)


@contextmanager
def production_lock(config: SyncConfig, operation: str, *, target: str | None = None, clock: Clock = utc_now) -> Iterator[dict[str, Any]]:
    """Hold the production lock for the ``with`` block, or raise :class:`OperationLocked` immediately.

    Raises :class:`LockError` when the lock location is missing or unsafe. Released on exit, whatever happens."""
    if operation not in OPERATIONS:
        raise ValueError(f"unknown production operation {operation!r}")
    fd = _open_lock_file(config)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OperationLocked(operation, _read_holder(fd), _iso(clock())) from None
        except OSError:
            raise LockError("the operating system refused the lock") from None
        metadata = {"lock_version": LOCK_VERSION, "operation": operation, "pid": os.getpid(), "hostname": socket.gethostname(),
                    "acquired_at": _iso(clock()), "target": safe_target(target)}
        try:
            _write_metadata(fd, metadata)   # diagnostic only; the flock above is what makes this process the holder
            yield metadata
        finally:
            try:
                os.ftruncate(fd, 0)   # a clean release leaves no metadata; a crash may leave some, which proves nothing
            except OSError:
                pass
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
