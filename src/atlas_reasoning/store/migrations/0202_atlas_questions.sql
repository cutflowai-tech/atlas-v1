-- Phase 13: Atlas questions and management answers (Chat 3 range 0200-0299). atlas_questions / atlas_answers are created by 0001.

ALTER TABLE atlas_questions
    ADD COLUMN result_version      integer CHECK (result_version >= 1),
    ADD COLUMN ask_count           integer NOT NULL DEFAULT 1 CHECK (ask_count >= 1),
    ADD COLUMN last_asked_run_id   text REFERENCES reasoning_runs (run_id),
    ADD COLUMN last_asked_at       timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN resolved_by         text,
    ADD COLUMN dismiss_reason      text CHECK (dismiss_reason IS NULL OR length(dismiss_reason) BETWEEN 1 AND 2000);

ALTER TABLE atlas_questions
    ADD CONSTRAINT atlas_questions_dismissal CHECK (state = 'dismissed' OR dismiss_reason IS NULL),
    ADD CONSTRAINT atlas_questions_result_version CHECK ((result_id IS NULL) = (result_version IS NULL));

CREATE INDEX atlas_questions_case_idx ON atlas_questions (case_id, dedup_key);
CREATE INDEX atlas_questions_result_idx ON atlas_questions (result_id);

-- A question never goes back to open, and an answered question is never dismissed (its answers stay the record).
CREATE OR REPLACE FUNCTION atlas_questions_transition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.state <> NEW.state AND NOT (
        (OLD.state = 'open' AND NEW.state IN ('answered', 'dismissed', 'superseded'))
    ) THEN
        RAISE EXCEPTION 'atlas_questions: % -> % is not allowed', OLD.state, NEW.state USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER atlas_questions_state_transition BEFORE UPDATE ON atlas_questions
    FOR EACH ROW EXECUTE FUNCTION atlas_questions_transition();

-- Every time a result version asks a question: created, repeated (deduplicated onto the open question) or suppressed (already
-- answered, dismissed, or answerable from deterministic evidence). Append-only, so repeated asking stays auditable.
CREATE TABLE atlas_question_asks (
    ask_id         text PRIMARY KEY CHECK (ask_id ~ '^qa_[0-9a-f]{32}$'),
    case_id        text NOT NULL REFERENCES reasoning_cases (case_id),
    result_id      text NOT NULL REFERENCES reasoning_results (result_id),
    result_version integer NOT NULL CHECK (result_version >= 1),
    run_id         text REFERENCES reasoning_runs (run_id),
    dedup_key      text NOT NULL CHECK (dedup_key <> ''),
    question_id    text REFERENCES atlas_questions (question_id),
    outcome        text NOT NULL CHECK (outcome IN ('created', 'repeated', 'suppressed_answered', 'suppressed_dismissed', 'suppressed_evidence')),
    question_text  text NOT NULL CHECK (length(question_text) BETWEEN 1 AND 400),
    asked_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (result_id, result_version, dedup_key),
    CHECK ((outcome = 'suppressed_evidence') = (question_id IS NULL))
);
CREATE INDEX atlas_question_asks_case_idx ON atlas_question_asks (case_id, dedup_key);
CREATE TRIGGER atlas_question_asks_append_only BEFORE UPDATE OR DELETE ON atlas_question_asks
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
