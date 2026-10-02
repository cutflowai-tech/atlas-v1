-- Atlas Reasoning V3, Phase 09 (Chat 2 range 0100-0199): lifecycle transition history (REV/09 #2, #8, #9).
--
-- One row per lifecycle transition of a result: from and to status, the reason code (atlas_reasoning.lifecycle), its detail, the
-- run and work item that caused it, the policy version and the result version that carries the new status. The CHECK below is the
-- transition table of atlas_reasoning.lifecycle.TRANSITIONS (tests/test_reasoning_lifecycle.py keeps them equal). A superseded
-- transition names the replacing case and result. Append-only.

CREATE TABLE reasoning_lifecycle_transitions (
    transition_id           text PRIMARY KEY CHECK (transition_id ~ '^lt_[0-9a-f]{32}$'),
    result_id               text NOT NULL,
    case_id                 text NOT NULL,
    result_version          integer NOT NULL CHECK (result_version >= 1),
    from_status             text CHECK (from_status IN ('new', 'active', 'updated', 'cooling', 'resolved', 'superseded')),
    to_status               text NOT NULL CHECK (to_status IN ('new', 'active', 'updated', 'cooling', 'resolved', 'superseded')),
    reason_code             text NOT NULL CHECK (reason_code <> ''),
    reason_detail           jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(reason_detail) = 'object'),
    policy_version          text NOT NULL,
    run_id                  text REFERENCES reasoning_runs (run_id),
    work_item_id            text REFERENCES reasoning_work_items (work_item_id),
    superseded_by_case_id   text REFERENCES reasoning_cases (case_id),
    superseded_by_result_id text REFERENCES reasoning_results (result_id),
    created_at              timestamptz NOT NULL,
    UNIQUE (result_id, result_version),
    FOREIGN KEY (result_id, case_id) REFERENCES reasoning_results (result_id, case_id),
    FOREIGN KEY (result_id, result_version) REFERENCES reasoning_result_versions (result_id, version),
    CHECK ((from_status IS NULL) = (result_version = 1)),
    CHECK ((to_status = 'superseded') = (superseded_by_result_id IS NOT NULL AND superseded_by_case_id IS NOT NULL)),
    CHECK (superseded_by_result_id IS NULL OR superseded_by_result_id <> result_id),
    CHECK (COALESCE(from_status, '-') || '>' || to_status || ':' || reason_code IN (
        '->new:created', 'active>cooling:not_in_snapshot', 'active>resolved:direct_fact_no_longer_true', 'active>superseded:superseded',
        'active>updated:patch_accepted', 'cooling>active:reappeared', 'cooling>resolved:absent_for_configured_runs',
        'cooling>resolved:direct_fact_no_longer_true', 'cooling>superseded:superseded', 'new>active:observed_again', 'new>cooling:not_in_snapshot',
        'new>resolved:direct_fact_no_longer_true', 'new>superseded:superseded', 'new>updated:patch_accepted',
        'resolved>active:reappeared_after_resolution', 'updated>active:update_settled', 'updated>cooling:not_in_snapshot',
        'updated>resolved:direct_fact_no_longer_true', 'updated>superseded:superseded'))
);
CREATE INDEX reasoning_lifecycle_transitions_case_idx ON reasoning_lifecycle_transitions (case_id, created_at);
CREATE INDEX reasoning_lifecycle_transitions_run_idx ON reasoning_lifecycle_transitions (run_id);
CREATE TRIGGER reasoning_lifecycle_transitions_append_only BEFORE UPDATE OR DELETE ON reasoning_lifecycle_transitions
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
