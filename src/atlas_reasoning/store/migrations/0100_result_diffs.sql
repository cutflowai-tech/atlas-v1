-- Atlas Reasoning V3, Phase 08 (Chat 2 range 0100-0199): before/after diffs of every appended result version (REV/08 #10).
--
-- One row per version after the first: which patchable fields changed (with before and after values) and which provenance fields
-- moved (version, evidence fingerprint, snapshot, lifecycle, model, prompt). A no-change review lists no changed field; a patch at
-- least one. Append-only, like the versions themselves.

CREATE TABLE reasoning_result_diffs (
    result_id        text NOT NULL,
    from_version     integer NOT NULL CHECK (from_version >= 1),
    to_version       integer NOT NULL,
    change_kind      text NOT NULL CHECK (change_kind IN ('patched', 'no_change_review', 'lifecycle')),
    changed_fields   text[] NOT NULL,
    field_diffs      jsonb NOT NULL CHECK (jsonb_typeof(field_diffs) = 'object'),
    provenance_diffs jsonb NOT NULL CHECK (jsonb_typeof(provenance_diffs) = 'object'),
    patch_version    text NOT NULL,
    run_id           text REFERENCES reasoning_runs (run_id),
    work_item_id     text REFERENCES reasoning_work_items (work_item_id),
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (result_id, to_version),
    FOREIGN KEY (result_id, from_version) REFERENCES reasoning_result_versions (result_id, version),
    FOREIGN KEY (result_id, to_version) REFERENCES reasoning_result_versions (result_id, version),
    CHECK (to_version = from_version + 1),
    CHECK (changed_fields <@ ARRAY['title', 'observation', 'reasoning_summary', 'supporting_evidence', 'counter_evidence', 'interpretation',
                                   'alternative_explanations', 'confidence', 'limitations', 'management_significance', 'questions_for_management',
                                   'suggested_investigations']::text[]),
    CHECK (change_kind <> 'patched' OR cardinality(changed_fields) >= 1),
    CHECK (change_kind = 'patched' OR cardinality(changed_fields) = 0)
);
CREATE INDEX reasoning_result_diffs_run_idx ON reasoning_result_diffs (run_id);
CREATE TRIGGER reasoning_result_diffs_append_only BEFORE UPDATE OR DELETE ON reasoning_result_diffs
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
