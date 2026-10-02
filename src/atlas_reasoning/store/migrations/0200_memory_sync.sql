-- Phase 10: Honcho synchronization bookkeeping (Chat 3 range 0200-0299). memory_sync_log itself is created by 0001; this adds what
-- the sync service needs to retry and audit copies. The canonical row (note, answer, question, teaching, result) is always committed
-- before its memory_sync_log row is written, and a failed copy never touches the canonical row.

ALTER TABLE memory_sync_log
    ADD COLUMN backend         text,
    ADD COLUMN peer_id         text,
    ADD COLUMN last_attempt_at timestamptz,
    ADD COLUMN retired_at      timestamptz;

ALTER TABLE memory_sync_log
    ADD CONSTRAINT memory_sync_log_synced_has_ref CHECK (status <> 'synced' OR operation <> 'write' OR external_ref IS NOT NULL),
    ADD CONSTRAINT memory_sync_log_attempted CHECK (attempts = 0 OR last_attempt_at IS NOT NULL);

CREATE INDEX memory_sync_log_source_idx ON memory_sync_log (source_type, source_id);
CREATE INDEX memory_sync_log_session_idx ON memory_sync_log (session_key) WHERE status = 'synced';

CREATE TRIGGER memory_sync_log_identity_immutable BEFORE UPDATE ON memory_sync_log
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('sync_id', 'source_type', 'source_id', 'session_key', 'operation',
                                                                 'content_sha256', 'created_at');
