# Atlas Reasoning V3 — Phase 15: Implement Reasoning Validation and Safety Guardrails

## Document purpose
This file is an implementation specification for the code builder. Treat every MUST/MUST NOT statement as binding. Do not infer additional product behavior that is not written here.

## Global architectural rules
- The existing deterministic Atlas pipeline remains the source of truth.
- Monday data, cycle reconstruction, metrics, Interpretation 1.5, Intelligence V2, confidence, and evidence remain upstream and must not be weakened.
- LLM output MUST NOT become the source of truth for metrics, source events, actor attribution, sample sizes, deadlines, or evidence identity.
- PostgreSQL is the canonical store for Reasoning V3 application state.
- Honcho is contextual memory, not the canonical database.
- The UI may display LLM reasoning summaries, but MUST NOT expose raw hidden chain-of-thought.
- All new outputs MUST remain traceable to upstream deterministic evidence.
- Existing behavior MUST remain unchanged when Reasoning V3 is disabled.

## Objective
Block unsupported or unsafe LLM output before it becomes canonical or visible.

## Scope
Grounding validation, policy validation, failure preservation, optional reviewer, and retry rules.

## Required implementation
1. Validate case/result identity.
2. Validate all evidence references exist.
3. Validate structured numeric claims against supplied evidence where possible.
4. Validate person/project references belong to the case.
5. Reject unsupported new metric names.
6. Detect or flag causal language when the upstream evidence only supports association.
7. Reject unsupported blame, personality, psychological, salary, termination, or HR judgment language.
8. Ensure confidence does not exceed what the contract allows.
9. Ensure manager teachings remain attributed as management context.
10. Require at least one supporting deterministic evidence reference for every visible conclusion.
11. Run deterministic validation before canonical merge.
12. Optionally run a second LLM reviewer for configured high-impact cases, but never use it as the sole validator.
13. Failed candidates MUST NOT replace the last valid result.
14. Persist failed candidates and validation errors for debugging.

## Required deliverables
Validation engine, error taxonomy, optional reviewer interface, failed-candidate storage, retry policy, and documentation.

## Required tests
Hallucinated project/person, unsupported metric, causal overclaim, failed-candidate preservation, teaching attribution, and valid pass.

## Acceptance criteria
No LLM result becomes canonical without deterministic grounding checks.

## Explicit non-goals
No dashboard redesign. No executive synthesis.

## Stop condition
Stop when invalid model output fails safely and the previous valid card remains active.
