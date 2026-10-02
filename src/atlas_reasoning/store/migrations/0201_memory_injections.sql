-- Phase 11: which human context and memory was injected into each reasoning call (Chat 3 range 0200-0299). Append-only.
-- request_id is the gateway request ID of the call (llm_calls.request_id); it is not a foreign key because the injection is recorded
-- before the call is made (the call row is written when the call ends, and a failed recording never loses the result).

CREATE TABLE memory_injections (
    injection_id    text PRIMARY KEY CHECK (injection_id ~ '^mi_[0-9a-f]{32}$'),
    case_id         text NOT NULL REFERENCES reasoning_cases (case_id),
    result_id       text REFERENCES reasoning_results (result_id),
    run_id          text REFERENCES reasoning_runs (run_id),
    work_item_id    text REFERENCES reasoning_work_items (work_item_id),
    request_id      text UNIQUE CHECK (request_id <> ''),
    purpose         text NOT NULL CHECK (purpose <> ''),
    assembler_version text NOT NULL,
    memory_status   text NOT NULL CHECK (memory_status IN ('not_requested', 'available', 'degraded', 'unavailable')),
    degraded_reason text,
    sessions        text[] NOT NULL,
    budget          jsonb NOT NULL CHECK (jsonb_typeof(budget) = 'object'),
    selected        jsonb NOT NULL CHECK (jsonb_typeof(selected) = 'array'),
    dropped         jsonb NOT NULL CHECK (jsonb_typeof(dropped) = 'object'),
    context_sha256  text NOT NULL CHECK (context_sha256 ~ '^[0-9a-f]{64}$'),
    created_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((memory_status = 'degraded') = (degraded_reason IS NOT NULL))
);
CREATE INDEX memory_injections_case_idx ON memory_injections (case_id, created_at);
CREATE INDEX memory_injections_run_idx ON memory_injections (run_id);
CREATE TRIGGER memory_injections_append_only BEFORE UPDATE OR DELETE ON memory_injections
    FOR EACH ROW EXECUTE FUNCTION reasoning_forbid_change();
