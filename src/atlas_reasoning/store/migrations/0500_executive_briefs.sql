-- Atlas Reasoning V3, Phase 17 (range 0500-0599): the executive brief, versioned by run (REV/17 #1, #5, #7, #8, #9).
--
-- An executive brief is synthesized only from canonical reasoning results. One brief identity per scope ('company'); its content
-- lives in append-only versions. Every version records the canonical result versions it was synthesized from
-- (executive_brief_inputs) and every result each statement references (executive_statement_refs). The foreign keys make the
-- grounding structural: a statement can only reference a result that was part of its version's input, and an input row can only name
-- an existing canonical result version - never a refused candidate, an Intelligence V2 finding or an evidence record.
-- executive_brief_runs audits every synthesis run: synthesized, synthesized_empty, unchanged (preserved without a model call) or
-- failed (the current brief preserved). A refused executive candidate is kept there for debugging only, never as a version.

CREATE TABLE executive_briefs (
    brief_id        text PRIMARY KEY CHECK (brief_id ~ '^eb1_[0-9a-f]{32}$'),
    scope           text NOT NULL UNIQUE CHECK (scope IN ('company')),
    current_version integer NOT NULL CHECK (current_version >= 1),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (updated_at >= created_at)
);
CREATE TRIGGER executive_briefs_identity_immutable BEFORE UPDATE ON executive_briefs
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_column_change('brief_id', 'scope', 'created_at');
CREATE TRIGGER executive_briefs_no_delete BEFORE DELETE ON executive_briefs
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

CREATE TABLE executive_brief_versions (
    brief_id          text NOT NULL REFERENCES executive_briefs (brief_id),
    version           integer NOT NULL CHECK (version >= 1),
    run_id            text NOT NULL REFERENCES reasoning_runs (run_id),
    input_version     text NOT NULL CHECK (input_version <> ''),
    input_fingerprint text NOT NULL CHECK (input_fingerprint ~ '^ei1_[0-9a-f]{64}$'),
    generator         text NOT NULL CHECK (generator IN ('model', 'deterministic_empty')),
    provider          text,
    model             text,
    prompt_version    text,
    validator_version text NOT NULL,
    document          jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    created_at        timestamptz NOT NULL,
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (brief_id, version),
    CHECK (document ->> 'brief_id' = brief_id AND (document ->> 'version')::integer = version AND document ->> 'run_id' = run_id),
    CHECK (document ->> 'input_fingerprint' = input_fingerprint AND document -> 'generator' ->> 'kind' = generator),
    CHECK ((generator = 'model') = (model IS NOT NULL AND provider IS NOT NULL AND prompt_version IS NOT NULL))
);
CREATE INDEX executive_brief_versions_run_idx ON executive_brief_versions (run_id);
CREATE TRIGGER executive_brief_versions_append_only BEFORE UPDATE OR DELETE ON executive_brief_versions
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
ALTER TABLE executive_briefs ADD CONSTRAINT executive_briefs_current_version_fk
    FOREIGN KEY (brief_id, current_version) REFERENCES executive_brief_versions (brief_id, version) DEFERRABLE INITIALLY DEFERRED;

-- The canonical result versions a brief version was synthesized from (its whole input, in input order).
CREATE TABLE executive_brief_inputs (
    brief_id         text NOT NULL,
    version          integer NOT NULL,
    result_id        text NOT NULL REFERENCES reasoning_results (result_id),
    result_version   integer NOT NULL CHECK (result_version >= 1),
    lifecycle_status text NOT NULL CHECK (lifecycle_status IN ('new', 'active', 'updated', 'resolved')),
    position         integer NOT NULL CHECK (position >= 1),
    PRIMARY KEY (brief_id, version, result_id),
    UNIQUE (brief_id, version, position),
    FOREIGN KEY (brief_id, version) REFERENCES executive_brief_versions (brief_id, version),
    FOREIGN KEY (result_id, result_version) REFERENCES reasoning_result_versions (result_id, version)
);
CREATE INDEX executive_brief_inputs_result_idx ON executive_brief_inputs (result_id);
-- An input row's lifecycle is the lifecycle of the canonical result version it names (not just any eligible value).
CREATE OR REPLACE FUNCTION executive_brief_input_lifecycle() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM reasoning_result_versions v
                   WHERE v.result_id = NEW.result_id AND v.version = NEW.result_version AND v.lifecycle_status = NEW.lifecycle_status) THEN
        RAISE EXCEPTION 'atlas_reasoning.executive_brief_inputs: % version % is not %', NEW.result_id, NEW.result_version, NEW.lifecycle_status
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER executive_brief_inputs_lifecycle BEFORE INSERT ON executive_brief_inputs
    FOR EACH ROW EXECUTE FUNCTION executive_brief_input_lifecycle();
CREATE TRIGGER executive_brief_inputs_append_only BEFORE UPDATE OR DELETE ON executive_brief_inputs
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

-- Every canonical result each statement references (statement -> result IDs; no UI URL is stored).
CREATE TABLE executive_statement_refs (
    brief_id     text NOT NULL,
    version      integer NOT NULL,
    section      text NOT NULL CHECK (section IN ('what_changed', 'top_concerns', 'important_improvements', 'system_patterns', 'editor_context',
                                                  'unresolved_questions', 'uncertainty', 'inspect_next')),
    statement_id text NOT NULL CHECK (statement_id ~ '^[a-z_]+-[1-9][0-9]*$'),
    result_id    text NOT NULL,
    PRIMARY KEY (brief_id, version, statement_id, result_id),
    CHECK (statement_id LIKE section || '-%'),
    FOREIGN KEY (brief_id, version, result_id) REFERENCES executive_brief_inputs (brief_id, version, result_id)
);
CREATE INDEX executive_statement_refs_result_idx ON executive_statement_refs (result_id);
CREATE TRIGGER executive_statement_refs_append_only BEFORE UPDATE OR DELETE ON executive_statement_refs
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();

-- One row per synthesis run: what the preserve policy decided and which version is current afterwards.
CREATE TABLE executive_brief_runs (
    synthesis_id       text PRIMARY KEY CHECK (synthesis_id ~ '^xs_[0-9a-f]{32}$'),
    run_id             text NOT NULL REFERENCES reasoning_runs (run_id),
    scope              text NOT NULL CHECK (scope IN ('company')),
    decision           text NOT NULL CHECK (decision IN ('synthesized', 'synthesized_empty', 'unchanged', 'failed')),
    policy_version     text NOT NULL,
    input_fingerprint  text CHECK (input_fingerprint ~ '^ei1_[0-9a-f]{64}$'),
    brief_id           text REFERENCES executive_briefs (brief_id),
    brief_version      integer,
    llm_calls          integer NOT NULL DEFAULT 0 CHECK (llm_calls >= 0),
    failure            text,
    error_codes        text[] NOT NULL DEFAULT '{}',
    violations         jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(violations) = 'array'),
    rejected_candidate jsonb CHECK (rejected_candidate IS NULL OR jsonb_typeof(rejected_candidate) = 'object'),
    candidate_omitted  text,
    model              text,
    prompt_version     text,
    request_ids        text[] NOT NULL DEFAULT '{}',
    created_at         timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (brief_id, brief_version) REFERENCES executive_brief_versions (brief_id, version),
    CHECK ((brief_id IS NULL) = (brief_version IS NULL)),
    CHECK ((decision = 'failed') = (failure IS NOT NULL)),
    CHECK (decision = 'failed' OR (brief_id IS NOT NULL AND input_fingerprint IS NOT NULL)),
    CHECK (decision IN ('synthesized', 'failed') OR llm_calls = 0),
    CHECK (rejected_candidate IS NULL OR decision = 'failed'),
    CHECK (candidate_omitted IS NULL OR rejected_candidate IS NULL)
);
CREATE INDEX executive_brief_runs_run_idx ON executive_brief_runs (run_id, created_at);
CREATE TRIGGER executive_brief_runs_append_only BEFORE UPDATE OR DELETE ON executive_brief_runs
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
