-- Atlas Reasoning V3, Phase 15 (range 0300-0399): candidates the validation and safety guardrails refused (REV/15 #13-14).
--
-- One row per refused candidate (a model answer turned into a complete ReasoningResult candidate, or an update and its merged
-- version) with the stable validation codes, every violation and the validator version. A refused candidate never becomes a result
-- version: the previous valid result stays current. Debugging only - never shown on the management dashboard. The candidate is the
-- contract-shaped structured output (no hidden reasoning exists to store; no secrets). Append-only.

CREATE TABLE reasoning_failed_candidates (
    candidate_id      text PRIMARY KEY CHECK (candidate_id ~ '^fc_[0-9a-f]{32}$'),
    case_id           text NOT NULL REFERENCES reasoning_cases (case_id),
    run_id            text REFERENCES reasoning_runs (run_id),
    work_item_id      text REFERENCES reasoning_work_items (work_item_id),
    result_id         text CHECK (result_id ~ '^rr1_[0-9a-f]{32}$'),      -- not a foreign key: a refused new result never exists
    base_version      integer CHECK (base_version >= 1),                  -- the version an update would have replaced
    request_id        text NOT NULL CHECK (request_id <> ''),
    purpose           text NOT NULL CHECK (purpose IN ('analyst', 'update')),
    attempt           integer NOT NULL CHECK (attempt >= 1),
    validator_version text NOT NULL,
    error_codes       text[] NOT NULL CHECK (cardinality(error_codes) >= 1),
    violations        jsonb NOT NULL CHECK (jsonb_typeof(violations) = 'array'),
    model             text,
    prompt_version    text,
    evidence_fingerprint text,
    candidate         jsonb CHECK (candidate IS NULL OR jsonb_typeof(candidate) = 'object'),
    candidate_omitted text,                                               -- why the candidate is not stored (too large)
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reasoning_failed_candidates_case_idx ON reasoning_failed_candidates (case_id, created_at);
CREATE INDEX reasoning_failed_candidates_work_idx ON reasoning_failed_candidates (work_item_id);
CREATE TRIGGER reasoning_failed_candidates_append_only BEFORE UPDATE OR DELETE ON reasoning_failed_candidates
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
