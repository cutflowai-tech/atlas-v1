from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path


class RawStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class RawRecord:
    name: str
    path: Path
    sha256: str
    size_bytes: int


def inside_git_worktree(path: Path) -> bool:
    """True when ``path`` is, or would be created, inside a Git checkout."""
    return any((parent / ".git").exists() for parent in [path, *path.parents])


_inside_git_worktree = inside_git_worktree


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_immutable(root: Path, name: str, data: bytes) -> RawRecord:
    """Write a raw payload once, outside git, read-only. Re-writing identical bytes is idempotent; different bytes fail."""
    root = root.expanduser().resolve()
    if _inside_git_worktree(root):
        raise RawStoreError(f"raw Monday payloads must be retained outside git: {root}")
    if Path(name).name != name:
        raise RawStoreError(f"raw payload name must be a plain file name: {name}")
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    digest = hashlib.sha256(data).hexdigest()
    if path.exists():
        if sha256_file(path) != digest:
            raise RawStoreError(f"refusing to overwrite immutable raw payload: {path}")
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return RawRecord(name=name, path=path, sha256=digest, size_bytes=len(data))


STAGING_SUFFIX = ".staging"


def write_immutable_atomic(root: Path, name: str, data: bytes) -> RawRecord:
    """Like :func:`write_immutable`, but the final name appears only once the full content is on disk.

    The bytes are written and flushed to a hidden staging file, then hard-linked to ``name``; a link never
    replaces an existing file, so a reader sees either no file or the complete one. Used for run artifacts
    (extract, manifest, failure record) whose presence has meaning."""
    root = root.expanduser().resolve()
    if _inside_git_worktree(root):
        raise RawStoreError(f"raw Monday payloads must be retained outside git: {root}")
    if Path(name).name != name or name.startswith("."):
        raise RawStoreError(f"raw payload name must be a plain file name: {name}")
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    digest = hashlib.sha256(data).hexdigest()
    staging = root / f".{name}.{os.getpid()}.{digest[:12]}{STAGING_SUFFIX}"
    fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        staging.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        try:
            os.link(staging, path)
        except FileExistsError:
            if sha256_file(path) != digest:
                raise RawStoreError(f"refusing to overwrite immutable raw payload: {path}") from None
    finally:
        staging.unlink(missing_ok=True)
    return RawRecord(name=name, path=path, sha256=digest, size_bytes=len(data))


def seal_existing(root: Path, name: str) -> RawRecord:
    """Register a payload already captured into the raw store (e.g. by the read-only Monday MCP connector)."""
    path = root.expanduser().resolve() / name
    if _inside_git_worktree(path.parent):
        raise RawStoreError(f"raw Monday payloads must be retained outside git: {path}")
    data = path.read_bytes()
    path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return RawRecord(name=name, path=path, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
