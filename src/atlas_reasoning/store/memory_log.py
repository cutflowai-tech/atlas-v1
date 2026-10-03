"""SQL for ``memory_sync_log``: one row per copy of canonical context written (or to be written) to contextual memory."""

from __future__ import annotations

import uuid
from typing import Any

from atlas_reasoning.enums import MemorySyncStatus
from atlas_reasoning.memory import MemoryRecord
from atlas_reasoning.store.repository import StoreTransaction


def new_sync_id() -> str:
    return f"ms_{uuid.uuid4().hex}"


def claim(tx: StoreTransaction, record: MemoryRecord, backend: str | None) -> dict[str, Any] | None:
    """Insert the log row for ``record`` if it is new, then lock it. ``None`` when another worker holds it right now."""
    tx._exec("""INSERT INTO memory_sync_log (sync_id, source_type, source_id, session_key, operation, content_sha256, status, backend, peer_id)
                VALUES (%s, %s, %s, %s, 'write', %s, 'pending', %s, %s)
                ON CONFLICT (source_type, source_id, session_key, operation, content_sha256) DO NOTHING""",
             (new_sync_id(), record.source_type, record.source_id, record.session_key, record.content_sha256, backend, record.peer_id))
    return tx._one("""SELECT * FROM memory_sync_log WHERE source_type = %s AND source_id = %s AND session_key = %s AND operation = 'write'
                      AND content_sha256 = %s FOR UPDATE SKIP LOCKED""",
                   (record.source_type, record.source_id, record.session_key, record.content_sha256))


def mark(tx: StoreTransaction, sync_id: str, status: MemorySyncStatus, *, backend: str | None, external_ref: str | None = None,
         error_class: str | None = None, attempted: bool = True) -> None:
    tx._exec("""UPDATE memory_sync_log SET status = %s, backend = COALESCE(%s, backend), external_ref = COALESCE(%s, external_ref),
                       error_class = %s, attempts = attempts + %s, last_attempt_at = CASE WHEN %s THEN now() ELSE last_attempt_at END,
                       synced_at = CASE WHEN %s = 'synced' THEN now() ELSE NULL END,
                       retired_at = CASE WHEN %s = 'synced' THEN NULL ELSE retired_at END, updated_at = now()
                WHERE sync_id = %s""",
             (status, backend, external_ref, error_class, 1 if attempted else 0, attempted, status, status, sync_id))


def live_copies(tx: StoreTransaction, source_type: str, source_id: str, session_key: str | None = None) -> list[dict[str, Any]]:
    """Synced, not yet retired copies of one canonical source (optionally in one session)."""
    if session_key is None:
        return tx._all("""SELECT * FROM memory_sync_log WHERE source_type = %s AND source_id = %s AND operation = 'write' AND status = 'synced'
                          AND retired_at IS NULL ORDER BY created_at, sync_id""", (source_type, source_id))
    return tx._all("""SELECT * FROM memory_sync_log WHERE source_type = %s AND source_id = %s AND session_key = %s AND operation = 'write'
                      AND status = 'synced' AND retired_at IS NULL ORDER BY created_at, sync_id""", (source_type, source_id, session_key))


def mark_retired(tx: StoreTransaction, sync_id: str) -> None:
    tx._exec("UPDATE memory_sync_log SET retired_at = now(), updated_at = now() WHERE sync_id = %s AND retired_at IS NULL", (sync_id,))


def unsynced(tx: StoreTransaction, limit: int) -> list[dict[str, Any]]:
    """Write rows still pending or failed, oldest first."""
    return tx._all("""SELECT * FROM memory_sync_log WHERE operation = 'write' AND status IN ('pending', 'failed')
                      ORDER BY created_at, sync_id LIMIT %s""", (limit,))


def rows(tx: StoreTransaction, *, source_type: str | None = None, source_id: str | None = None) -> list[dict[str, Any]]:
    clauses, params = [], []
    if source_type is not None:
        clauses.append("source_type = %s")
        params.append(source_type)
    if source_id is not None:
        clauses.append("source_id = %s")
        params.append(source_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return tx._all(f"SELECT * FROM memory_sync_log {where} ORDER BY created_at, sync_id", params)
