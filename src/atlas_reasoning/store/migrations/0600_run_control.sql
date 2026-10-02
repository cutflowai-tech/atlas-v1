-- Atlas Reasoning V3, Phase 18-A (range 0600-0629): run orchestration, per-pass reasoning-call budget, bounded resume.
--
-- reasoning_run_passes: one row per orchestration pass over a run (the initial pass after the Change Gate, then each resume). The
-- pass owns the run while open (at most one open pass per run, enforced by a partial unique index), accounts its provider calls
-- atomically against its budget (calls_used <= call_budget, enforced by a CHECK, so two workers can never overspend), and records the
-- run status it computed with the reasons. reasoning_runs.status stays the run's canonical final status.
--
-- reasoning_work_retries: the lineage of every retry work item that resume created for a failed one. Each failed item is retried at most
-- once (UNIQUE failed_work_item_id), and each (case, evidence state, attempt) exists once, so concurrent or repeated resumes can never
-- duplicate work. Both tables are additive; no earlier table changes.

CREATE TABLE reasoning_run_passes (
    pass_id        text PRIMARY KEY CHECK (pass_id ~ '^rp_[0-9a-f]{32}$'),
    run_id         text NOT NULL REFERENCES reasoning_runs (run_id),
    kind           text NOT NULL CHECK (kind IN ('initial', 'resume')),
    policy_version text NOT NULL,
    call_budget    integer CHECK (call_budget IS NULL OR call_budget >= 0),
    calls_used     integer NOT NULL DEFAULT 0 CHECK (calls_used >= 0),
    admitted       integer NOT NULL DEFAULT 0 CHECK (admitted >= 0),
    deferred       integer NOT NULL DEFAULT 0 CHECK (deferred >= 0),
    retries        integer NOT NULL DEFAULT 0 CHECK (retries >= 0),
    run_status     text CHECK (run_status IN ('complete', 'partial', 'degraded', 'failed')),
    reasons        text[] NOT NULL DEFAULT '{}',
    counts         jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(counts) = 'object'),
    outcome        text CHECK (outcome IN ('finished', 'interrupted')),
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    CHECK (call_budget IS NULL OR calls_used <= call_budget),
    CHECK ((finished_at IS NULL) = (outcome IS NULL)),
    CHECK (outcome IS DISTINCT FROM 'finished' OR run_status IS NOT NULL)
);
CREATE UNIQUE INDEX reasoning_run_passes_one_open ON reasoning_run_passes (run_id) WHERE finished_at IS NULL;
CREATE INDEX reasoning_run_passes_run_idx ON reasoning_run_passes (run_id, started_at);
CREATE TRIGGER reasoning_run_passes_identity_immutable BEFORE UPDATE ON reasoning_run_passes
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('pass_id', 'run_id', 'kind', 'policy_version', 'call_budget', 'started_at');
CREATE TRIGGER reasoning_run_passes_no_delete BEFORE DELETE ON reasoning_run_passes
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

CREATE TABLE reasoning_work_retries (
    retry_work_item_id   text PRIMARY KEY REFERENCES reasoning_work_items (work_item_id),
    failed_work_item_id  text NOT NULL UNIQUE REFERENCES reasoning_work_items (work_item_id),
    case_id              text NOT NULL REFERENCES reasoning_cases (case_id),
    evidence_fingerprint text NOT NULL CHECK (evidence_fingerprint ~ '^ef1_[0-9a-f]{64}$'),
    attempt              integer NOT NULL CHECK (attempt >= 2),
    failure              text NOT NULL CHECK (failure <> ''),
    pass_id              text NOT NULL REFERENCES reasoning_run_passes (pass_id),
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (case_id, evidence_fingerprint, attempt),
    CHECK (retry_work_item_id <> failed_work_item_id)
);
CREATE INDEX reasoning_work_retries_case_idx ON reasoning_work_retries (case_id, evidence_fingerprint);
CREATE TRIGGER reasoning_work_retries_append_only BEFORE UPDATE OR DELETE ON reasoning_work_retries
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
