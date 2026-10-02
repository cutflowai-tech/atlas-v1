-- Phase 14: Teach Atlas (Chat 3 range 0200-0299). teachings / teaching_revisions are created by 0001.

ALTER TABLE teachings
    ADD COLUMN affects_source_data boolean NOT NULL DEFAULT false,
    ADD COLUMN status_changed_by   text,
    ADD COLUMN status_changed_at   timestamptz;

ALTER TABLE teachings
    ADD CONSTRAINT teachings_source_data_flag CHECK (NOT affects_source_data OR teaching_type = 'correction'),
    ADD CONSTRAINT teachings_validity_bounds CHECK (validity_mode = 'until_changed' OR (valid_from IS NOT NULL AND valid_until IS NOT NULL)),
    ADD CONSTRAINT teachings_until_changed_open CHECK (validity_mode <> 'until_changed' OR valid_until IS NULL);

CREATE INDEX teachings_status_idx ON teachings (status, scope_type);

-- Archived is final: an archived teaching stays readable for audit and never becomes active (or anything else) again. Scope never
-- changes: a teaching for another subject is a new teaching.
CREATE OR REPLACE FUNCTION teachings_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'archived' THEN
        RAISE EXCEPTION 'teachings: archived teaching % cannot change', OLD.teaching_id USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.scope_type IS DISTINCT FROM OLD.scope_type OR NEW.scope_id IS DISTINCT FROM OLD.scope_id THEN
        RAISE EXCEPTION 'teachings: the scope of % is immutable', OLD.teaching_id USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'teachings: every change of % is a new revision', OLD.teaching_id USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER teachings_guard BEFORE UPDATE ON teachings FOR EACH ROW EXECUTE FUNCTION teachings_guard();
CREATE TRIGGER teachings_no_delete BEFORE DELETE ON teachings FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

-- A correction that says upstream (Monday / pipeline) data is wrong is surfaced to engineering here. Atlas never edits evidence or
-- metrics because of it; engineering decides whether the source data or the pipeline must change.
CREATE TABLE engineering_review_flags (
    flag_id          text PRIMARY KEY CHECK (flag_id ~ '^erf_[0-9a-f]{32}$'),
    source_type      text NOT NULL CHECK (source_type = 'management_teaching'),
    source_id        text NOT NULL REFERENCES teachings (teaching_id),
    source_revision  integer NOT NULL CHECK (source_revision >= 1),
    summary          text NOT NULL CHECK (length(summary) BETWEEN 1 AND 8000),
    raised_by        text,
    status           text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved')),
    resolution       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    CHECK (status <> 'resolved' OR resolution IS NOT NULL)
);
CREATE UNIQUE INDEX engineering_review_flags_one_open ON engineering_review_flags (source_type, source_id) WHERE status <> 'resolved';
CREATE TRIGGER engineering_review_flags_identity_immutable BEFORE UPDATE ON engineering_review_flags
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('flag_id', 'source_type', 'source_id', 'source_revision', 'summary', 'raised_by',
                                                                 'created_at');
