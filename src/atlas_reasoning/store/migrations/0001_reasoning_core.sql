-- Atlas Reasoning V3 canonical state (REV/03). Schema atlas_reasoning; PostgreSQL 14+.
--
-- Canonical identifiers and statuses are relational columns with CHECK constraints mirroring atlas_reasoning.enums; JSONB holds
-- only document-shaped content (contract documents, canonical evidence, deltas, reason details). History tables are append-only.
-- Monday raw operational data is never copied here: evidence is referenced by Monday item, cycle and event IDs.

CREATE OR REPLACE FUNCTION reasoning_forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'atlas_reasoning.%: rows are append-only (% refused)', TG_TABLE_NAME, TG_OP USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE OR REPLACE FUNCTION reasoning_forbid_column_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    column_name text;
BEGIN
    FOREACH column_name IN ARRAY TG_ARGV LOOP
        IF to_jsonb(NEW) -> column_name IS DISTINCT FROM to_jsonb(OLD) -> column_name THEN
            RAISE EXCEPTION 'atlas_reasoning.%.% is immutable', TG_TABLE_NAME, column_name USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;

-- One reasoning run over one source snapshot.
CREATE TABLE reasoning_runs (
    run_id                    text PRIMARY KEY CHECK (run_id ~ '^run_[0-9a-f]{32}$'),
    source_snapshot_id        text NOT NULL CHECK (source_snapshot_id <> ''),
    release_id                text,
    upstream_contract_version text NOT NULL,
    intelligence_version      text NOT NULL,
    boundary_version          text NOT NULL,
    identity_version          text NOT NULL,
    fingerprint_version       text NOT NULL,
    status                    text NOT NULL CHECK (status IN ('started', 'gated', 'complete', 'partial', 'degraded', 'failed')),
    counts                    jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(counts) = 'object'),
    error                     text,
    started_at                timestamptz NOT NULL DEFAULT now(),
    gated_at                  timestamptz,
    finished_at               timestamptz,
    CHECK (gated_at IS NULL OR gated_at >= started_at),
    CHECK (finished_at IS NULL OR finished_at >= started_at),
    CHECK (status <> 'gated' OR gated_at IS NOT NULL)
);
CREATE INDEX reasoning_runs_snapshot_idx ON reasoning_runs (source_snapshot_id);
CREATE INDEX reasoning_runs_started_idx ON reasoning_runs (started_at DESC);
CREATE TRIGGER reasoning_runs_immutable BEFORE UPDATE ON reasoning_runs
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('run_id', 'source_snapshot_id', 'started_at');

-- One stable management issue. Identity columns never change after insert; observation columns follow the Change Gate.
CREATE TABLE reasoning_cases (
    case_id                   text PRIMARY KEY CHECK (case_id ~ '^rc1_[0-9a-f]{32}$'),
    identity_version          text NOT NULL,
    identity_key              text NOT NULL UNIQUE,
    case_type                 text NOT NULL CHECK (case_type IN ('editor_pattern', 'team_pattern', 'video_type_pattern', 'workflow_pattern',
                                                                 'open_work_risk', 'project_risk', 'data_quality')),
    subject_type              text NOT NULL CHECK (subject_type IN ('editor', 'team', 'video_type', 'workflow_stage', 'project', 'data_source')),
    subject_id                text NOT NULL CHECK (subject_id <> ''),
    topic_key                 text NOT NULL CHECK (topic_key IN ('deadline', 'speed', 'quality', 'workload', 'runway', 'post_editor_delay',
                                                                 'workflow_time', 'component_conflict', 'hidden_signal', 'open_work_risk', 'data_quality')),
    video_type                text,
    workflow_stage            text,
    detector_family           text,
    signal                    text,
    first_seen_run_id         text NOT NULL REFERENCES reasoning_runs (run_id),
    last_seen_run_id          text NOT NULL REFERENCES reasoning_runs (run_id),
    last_observed_run_id      text NOT NULL REFERENCES reasoning_runs (run_id),
    last_evidence_fingerprint text NOT NULL CHECK (last_evidence_fingerprint ~ '^ef1_[0-9a-f]{64}$'),
    presence                  text NOT NULL CHECK (presence IN ('present', 'absent')),
    absent_since_run_id       text REFERENCES reasoning_runs (run_id),
    consecutive_absent_runs   integer NOT NULL DEFAULT 0 CHECK (consecutive_absent_runs >= 0),
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now(),
    CHECK ((presence = 'absent') = (absent_since_run_id IS NOT NULL)),
    CHECK ((presence = 'present') = (consecutive_absent_runs = 0))
);
CREATE INDEX reasoning_cases_subject_idx ON reasoning_cases (subject_type, subject_id);
CREATE INDEX reasoning_cases_topic_idx ON reasoning_cases (topic_key);
CREATE INDEX reasoning_cases_presence_idx ON reasoning_cases (presence);
CREATE TRIGGER reasoning_cases_identity_immutable BEFORE UPDATE ON reasoning_cases
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('case_id', 'identity_version', 'identity_key', 'case_type', 'subject_type',
                                                                 'subject_id', 'topic_key', 'video_type', 'workflow_stage', 'detector_family',
                                                                 'signal', 'first_seen_run_id', 'created_at');

-- Each distinct evidence state of a case, stored once: canonical evidence (what the fingerprint hashes) and the ReasoningCase
-- document built from it. Deltas between any two states can be recomputed from here.
CREATE TABLE reasoning_case_evidence (
    case_id              text NOT NULL REFERENCES reasoning_cases (case_id),
    evidence_fingerprint text NOT NULL CHECK (evidence_fingerprint ~ '^ef1_[0-9a-f]{64}$'),
    fingerprint_version  text NOT NULL,
    canonical_evidence   jsonb NOT NULL CHECK (jsonb_typeof(canonical_evidence) = 'object'),
    case_document        jsonb NOT NULL CHECK (case_document ->> 'case_id' = case_id AND case_document ->> 'evidence_fingerprint' = evidence_fingerprint),
    first_seen_run_id    text NOT NULL REFERENCES reasoning_runs (run_id),
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id, evidence_fingerprint)
);
CREATE TRIGGER reasoning_case_evidence_append_only BEFORE UPDATE OR DELETE ON reasoning_case_evidence
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
ALTER TABLE reasoning_cases ADD CONSTRAINT reasoning_cases_last_evidence_fk
    FOREIGN KEY (case_id, last_evidence_fingerprint) REFERENCES reasoning_case_evidence (case_id, evidence_fingerprint) DEFERRABLE INITIALLY DEFERRED;

-- Results: one row per result identity; its content lives in versions. At most one open result per case.
CREATE TABLE reasoning_results (
    result_id               text PRIMARY KEY CHECK (result_id ~ '^rr1_[0-9a-f]{32}$'),
    case_id                 text NOT NULL REFERENCES reasoning_cases (case_id),
    current_version         integer NOT NULL CHECK (current_version >= 1),
    lifecycle_status        text NOT NULL CHECK (lifecycle_status IN ('new', 'active', 'updated', 'cooling', 'resolved', 'superseded')),
    superseded_by_case_id   text REFERENCES reasoning_cases (case_id),
    superseded_by_result_id text REFERENCES reasoning_results (result_id),
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (result_id, case_id),
    CHECK ((lifecycle_status = 'superseded') = (superseded_by_result_id IS NOT NULL AND superseded_by_case_id IS NOT NULL)),
    CHECK (superseded_by_result_id IS NULL OR superseded_by_result_id <> result_id),
    CHECK (updated_at >= created_at)
);
CREATE UNIQUE INDEX reasoning_results_one_open_per_case ON reasoning_results (case_id)
    WHERE lifecycle_status IN ('new', 'active', 'updated', 'cooling');
CREATE TRIGGER reasoning_results_identity_immutable BEFORE UPDATE ON reasoning_results
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('result_id', 'case_id', 'created_at');

-- Gate-produced work for later phases. Only new_result / update_result may involve an LLM; at most one open item of each kind per case.
CREATE TABLE reasoning_work_items (
    work_item_id        text PRIMARY KEY CHECK (work_item_id ~ '^wi_[0-9a-f]{32}$'),
    run_id              text NOT NULL REFERENCES reasoning_runs (run_id),
    case_id             text NOT NULL REFERENCES reasoning_cases (case_id),
    kind                text NOT NULL CHECK (kind IN ('new_result', 'update_result', 'lifecycle')),
    gate_action         text NOT NULL CHECK (gate_action IN ('new', 'updated', 'disappeared')),
    status              text NOT NULL CHECK (status IN ('pending', 'in_progress', 'done', 'failed', 'superseded', 'cancelled')),
    requires_llm        boolean NOT NULL,
    result_id           text REFERENCES reasoning_results (result_id),
    base_result_version integer CHECK (base_result_version >= 1),
    fingerprint_before  text CHECK (fingerprint_before ~ '^ef1_[0-9a-f]{64}$'),
    fingerprint_after   text CHECK (fingerprint_after ~ '^ef1_[0-9a-f]{64}$'),
    material_delta      jsonb CHECK (material_delta IS NULL OR jsonb_typeof(material_delta) = 'object'),
    superseded_by       text REFERENCES reasoning_work_items (work_item_id) DEFERRABLE INITIALLY DEFERRED,
    attempts            integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error          text,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK (requires_llm = (kind IN ('new_result', 'update_result'))),
    CHECK ((status = 'superseded') = (superseded_by IS NOT NULL)),
    CHECK (kind <> 'new_result' OR (result_id IS NULL AND fingerprint_after IS NOT NULL)),
    CHECK (kind <> 'update_result' OR (result_id IS NOT NULL AND base_result_version IS NOT NULL AND fingerprint_before IS NOT NULL
                                       AND fingerprint_after IS NOT NULL AND fingerprint_before <> fingerprint_after AND material_delta IS NOT NULL)),
    FOREIGN KEY (case_id, fingerprint_after) REFERENCES reasoning_case_evidence (case_id, evidence_fingerprint)
);
CREATE UNIQUE INDEX reasoning_work_items_one_open_llm_item ON reasoning_work_items (case_id)
    WHERE status IN ('pending', 'in_progress') AND requires_llm;
CREATE UNIQUE INDEX reasoning_work_items_one_open_lifecycle_item ON reasoning_work_items (case_id)
    WHERE status IN ('pending', 'in_progress') AND NOT requires_llm;
CREATE INDEX reasoning_work_items_run_idx ON reasoning_work_items (run_id);
CREATE INDEX reasoning_work_items_open_idx ON reasoning_work_items (status) WHERE status IN ('pending', 'in_progress');
CREATE TRIGGER reasoning_work_items_identity_immutable BEFORE UPDATE ON reasoning_work_items
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('work_item_id', 'run_id', 'case_id', 'kind', 'gate_action', 'requires_llm',
                                                                 'fingerprint_before', 'fingerprint_after', 'created_at');

-- The Change Gate decision and its reason for every known case in every run (REV/05 #10).
CREATE TABLE reasoning_case_observations (
    run_id               text NOT NULL REFERENCES reasoning_runs (run_id),
    case_id              text NOT NULL REFERENCES reasoning_cases (case_id),
    action               text NOT NULL CHECK (action IN ('unchanged', 'new', 'updated', 'disappeared')),
    reason_code          text NOT NULL CHECK (reason_code <> ''),
    reason_detail        jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(reason_detail) = 'object'),
    evidence_fingerprint text,
    previous_fingerprint text CHECK (previous_fingerprint ~ '^ef1_[0-9a-f]{64}$'),
    material_delta       jsonb CHECK (material_delta IS NULL OR jsonb_typeof(material_delta) = 'object'),
    work_item_id         text REFERENCES reasoning_work_items (work_item_id),
    observed_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, case_id),
    FOREIGN KEY (case_id, evidence_fingerprint) REFERENCES reasoning_case_evidence (case_id, evidence_fingerprint),
    CHECK ((action = 'disappeared') = (evidence_fingerprint IS NULL)),
    CHECK (action <> 'new' OR previous_fingerprint IS NULL),
    CHECK (action <> 'unchanged' OR (previous_fingerprint IS NOT NULL AND previous_fingerprint = evidence_fingerprint AND work_item_id IS NULL)),
    CHECK (action <> 'updated' OR (previous_fingerprint IS NOT NULL AND previous_fingerprint <> evidence_fingerprint AND material_delta IS NOT NULL))
);
CREATE INDEX reasoning_case_observations_case_idx ON reasoning_case_observations (case_id, observed_at);
CREATE TRIGGER reasoning_case_observations_append_only BEFORE UPDATE OR DELETE ON reasoning_case_observations
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

-- Every version of every result, append-only. The current version must exist (deferred FK, checked at commit).
CREATE TABLE reasoning_result_versions (
    result_id            text NOT NULL REFERENCES reasoning_results (result_id),
    version              integer NOT NULL CHECK (version >= 1),
    change_kind          text NOT NULL CHECK (change_kind IN ('created', 'patched', 'no_change_review', 'lifecycle')),
    document             jsonb NOT NULL,
    update_document      jsonb,
    lifecycle_status     text NOT NULL CHECK (lifecycle_status IN ('new', 'active', 'updated', 'cooling', 'resolved', 'superseded')),
    evidence_fingerprint text NOT NULL CHECK (evidence_fingerprint ~ '^ef1_[0-9a-f]{64}$'),
    source_snapshot_id   text NOT NULL,
    provider             text NOT NULL,
    model                text NOT NULL,
    prompt_version       text NOT NULL,
    run_id               text REFERENCES reasoning_runs (run_id),
    work_item_id         text REFERENCES reasoning_work_items (work_item_id),
    reason               text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (result_id, version),
    CHECK (document ->> 'result_id' = result_id AND (document ->> 'version')::integer = version),
    CHECK (document ->> 'lifecycle_status' = lifecycle_status AND document ->> 'evidence_fingerprint' = evidence_fingerprint),
    CHECK ((change_kind = 'created') = (version = 1)),
    CHECK ((change_kind IN ('patched', 'no_change_review')) = (update_document IS NOT NULL))
);
CREATE INDEX reasoning_result_versions_run_idx ON reasoning_result_versions (run_id);
CREATE TRIGGER reasoning_result_versions_append_only BEFORE UPDATE OR DELETE ON reasoning_result_versions
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
ALTER TABLE reasoning_results ADD CONSTRAINT reasoning_results_current_version_fk
    FOREIGN KEY (result_id, current_version) REFERENCES reasoning_result_versions (result_id, version) DEFERRABLE INITIALLY DEFERRED;

-- Which deterministic evidence each result version cites, resolvable to Monday item, cycle and event IDs.
CREATE TABLE reasoning_evidence_links (
    result_id            text NOT NULL,
    version              integer NOT NULL,
    ref_id               text NOT NULL CHECK (ref_id ~ '^ev1_[0-9a-f]{24}$'),
    case_id              text NOT NULL,
    evidence_fingerprint text NOT NULL,
    member_key           text NOT NULL,
    finding_id           text NOT NULL,
    role                 text NOT NULL CHECK (role IN ('supporting', 'contradicting', 'context')),
    evidence_code        text NOT NULL,
    monday_item_id       text NOT NULL,
    cycle_id             text,
    event_ids            text[] NOT NULL CHECK (cardinality(event_ids) >= 1),
    cited_in             text[] NOT NULL CHECK (cardinality(cited_in) >= 1),
    PRIMARY KEY (result_id, version, ref_id),
    FOREIGN KEY (result_id, version) REFERENCES reasoning_result_versions (result_id, version),
    FOREIGN KEY (case_id, evidence_fingerprint) REFERENCES reasoning_case_evidence (case_id, evidence_fingerprint)
);
CREATE INDEX reasoning_evidence_links_item_idx ON reasoning_evidence_links (monday_item_id);
CREATE INDEX reasoning_evidence_links_case_idx ON reasoning_evidence_links (case_id);
CREATE TRIGGER reasoning_evidence_links_append_only BEFORE UPDATE OR DELETE ON reasoning_evidence_links
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

-- Manager interpretation notes on a result card (Phase 12). Context, never evidence. The note's case must be its result's case.
CREATE TABLE manager_notes (
    note_id     text PRIMARY KEY CHECK (note_id <> ''),
    result_id   text NOT NULL,
    case_id     text NOT NULL,
    author      text,
    body        text NOT NULL CHECK (length(body) BETWEEN 1 AND 8000),
    source_type text NOT NULL DEFAULT 'manager_interpretation' CHECK (source_type = 'manager_interpretation'),
    revision    integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (result_id, case_id) REFERENCES reasoning_results (result_id, case_id),
    CHECK (updated_at >= created_at)
);
CREATE INDEX manager_notes_result_idx ON manager_notes (result_id);
CREATE TRIGGER manager_notes_identity_immutable BEFORE UPDATE ON manager_notes
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('note_id', 'result_id', 'case_id', 'source_type', 'created_at');

CREATE TABLE manager_note_revisions (
    note_id     text NOT NULL REFERENCES manager_notes (note_id),
    revision    integer NOT NULL CHECK (revision >= 1),
    body        text NOT NULL CHECK (length(body) BETWEEN 1 AND 8000),
    author      text,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (note_id, revision)
);
CREATE TRIGGER manager_note_revisions_append_only BEFORE UPDATE OR DELETE ON manager_note_revisions
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

-- Questions Atlas asks management (Phase 13): at most one open question per case and deduplication key.
CREATE TABLE atlas_questions (
    question_id           text PRIMARY KEY CHECK (question_id <> ''),
    case_id               text NOT NULL REFERENCES reasoning_cases (case_id),
    result_id             text REFERENCES reasoning_results (result_id),
    dedup_key             text NOT NULL CHECK (dedup_key <> ''),
    question_text         text NOT NULL CHECK (length(question_text) BETWEEN 1 AND 400),
    reason                text NOT NULL CHECK (length(reason) BETWEEN 1 AND 2000),
    expected_context_type text NOT NULL CHECK (expected_context_type IN ('business_rule', 'workflow_context', 'assignment_context', 'client_context',
                                                                          'temporary_situation', 'data_correction', 'other')),
    state                 text NOT NULL CHECK (state IN ('open', 'answered', 'dismissed', 'superseded')),
    asked_in_run_id       text REFERENCES reasoning_runs (run_id),
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    resolved_at           timestamptz,
    CHECK ((state = 'open') = (resolved_at IS NULL))
);
CREATE UNIQUE INDEX atlas_questions_one_open ON atlas_questions (case_id, dedup_key) WHERE state = 'open';
CREATE TRIGGER atlas_questions_identity_immutable BEFORE UPDATE ON atlas_questions
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('question_id', 'case_id', 'dedup_key', 'created_at');

-- Management answers (Phase 13). History is preserved: a conflicting answer links to the one it conflicts with.
CREATE TABLE atlas_answers (
    answer_id                text PRIMARY KEY CHECK (answer_id <> ''),
    question_id              text NOT NULL REFERENCES atlas_questions (question_id),
    body                     text NOT NULL CHECK (length(body) BETWEEN 1 AND 8000),
    author                   text,
    source_type              text NOT NULL DEFAULT 'manager_answer' CHECK (source_type = 'manager_answer'),
    conflicts_with_answer_id text REFERENCES atlas_answers (answer_id),
    created_at               timestamptz NOT NULL DEFAULT now(),
    CHECK (conflicts_with_answer_id IS NULL OR conflicts_with_answer_id <> answer_id)
);
CREATE INDEX atlas_answers_question_idx ON atlas_answers (question_id);
CREATE TRIGGER atlas_answers_append_only BEFORE UPDATE OR DELETE ON atlas_answers
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

-- Teach Atlas (Phase 14): explicit, scoped, expirable management teachings. Never a change to Monday evidence or metrics.
CREATE TABLE teachings (
    teaching_id   text PRIMARY KEY CHECK (teaching_id <> ''),
    body          text NOT NULL CHECK (length(body) BETWEEN 1 AND 8000),
    scope_type    text NOT NULL CHECK (scope_type IN ('company', 'editor', 'video_type', 'workflow', 'client', 'specific_result')),
    scope_id      text,
    teaching_type text NOT NULL CHECK (teaching_type IN ('business_rule', 'context', 'correction', 'interpretation', 'temporary_situation')),
    validity_mode text NOT NULL CHECK (validity_mode IN ('until_changed', 'date_range', 'current_period')),
    valid_from    timestamptz,
    valid_until   timestamptz,
    status        text NOT NULL CHECK (status IN ('active', 'disabled', 'archived')),
    author        text,
    revision      integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CHECK ((scope_type = 'company') = (scope_id IS NULL)),
    CHECK (validity_mode <> 'date_range' OR (valid_from IS NOT NULL AND valid_until IS NOT NULL)),
    CHECK (valid_from IS NULL OR valid_until IS NULL OR valid_until > valid_from)
);
CREATE INDEX teachings_scope_idx ON teachings (scope_type, scope_id) WHERE status = 'active';
CREATE TRIGGER teachings_identity_immutable BEFORE UPDATE ON teachings
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('teaching_id', 'created_at');

CREATE TABLE teaching_revisions (
    teaching_id   text NOT NULL REFERENCES teachings (teaching_id),
    revision      integer NOT NULL CHECK (revision >= 1),
    snapshot      jsonb NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    author        text,
    recorded_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (teaching_id, revision)
);
CREATE TRIGGER teaching_revisions_append_only BEFORE UPDATE OR DELETE ON teaching_revisions
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

-- Provider-call metadata (Phase 06). Never prompts, responses or credentials.
CREATE TABLE llm_calls (
    call_id              text PRIMARY KEY CHECK (call_id ~ '^call_[0-9a-f]{32}$'),
    request_id           text NOT NULL UNIQUE CHECK (request_id <> ''),
    run_id               text REFERENCES reasoning_runs (run_id),
    case_id              text REFERENCES reasoning_cases (case_id),
    work_item_id         text REFERENCES reasoning_work_items (work_item_id),
    provider             text NOT NULL,
    model                text NOT NULL,
    prompt_version       text,
    source_snapshot_id   text,
    evidence_fingerprint text CHECK (evidence_fingerprint ~ '^ef1_[0-9a-f]{64}$'),
    purpose              text NOT NULL CHECK (purpose <> ''),
    status               text NOT NULL CHECK (status IN ('succeeded', 'failed')),
    provider_status      text,
    error_class          text,
    attempts             integer NOT NULL CHECK (attempts >= 1),
    retries              integer NOT NULL CHECK (retries >= 0 AND retries = attempts - 1),
    latency_ms           integer NOT NULL CHECK (latency_ms >= 0),
    input_tokens         integer CHECK (input_tokens >= 0),
    output_tokens        integer CHECK (output_tokens >= 0),
    provider_response_id text,
    started_at           timestamptz NOT NULL,
    finished_at          timestamptz NOT NULL,
    CHECK ((status = 'failed') = (error_class IS NOT NULL)),
    CHECK (finished_at >= started_at)
);
CREATE INDEX llm_calls_run_idx ON llm_calls (run_id);
CREATE INDEX llm_calls_case_idx ON llm_calls (case_id);
CREATE TRIGGER llm_calls_append_only BEFORE UPDATE OR DELETE ON llm_calls
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

-- Synchronization of canonical context to Honcho (Phase 10). The canonical row is written first; this log tracks the copy.
CREATE TABLE memory_sync_log (
    sync_id        text PRIMARY KEY CHECK (sync_id <> ''),
    source_type    text NOT NULL CHECK (source_type IN ('manager_interpretation', 'manager_answer', 'management_teaching', 'atlas_question',
                                                         'prior_reasoning_summary')),
    source_id      text NOT NULL CHECK (source_id <> ''),
    session_key    text NOT NULL CHECK (session_key <> ''),
    operation      text NOT NULL CHECK (operation IN ('write', 'delete')),
    content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    status         text NOT NULL CHECK (status IN ('pending', 'synced', 'failed', 'skipped')),
    attempts       integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    external_ref   text,
    error_class    text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    synced_at      timestamptz,
    UNIQUE (source_type, source_id, session_key, operation, content_sha256),
    CHECK ((status = 'synced') = (synced_at IS NOT NULL)),
    CHECK (status <> 'failed' OR error_class IS NOT NULL)
);
CREATE INDEX memory_sync_log_pending_idx ON memory_sync_log (status) WHERE status IN ('pending', 'failed');
