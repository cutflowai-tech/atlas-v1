# Atlas Reasoning V3 — Phase 11: Build the Scoped Memory Context Assembler

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
Select only relevant memory for each case and prevent cross-subject contamination.

## Scope
Context retrieval, filtering, budgeting, provenance, and deterministic serialization.

## Required implementation
1. Create `MemoryContextAssembler`.
2. Define allowed memory scopes by case type.
3. Editor cases may receive relevant global teachings, that editor's memory, relevant video-type memory, specific-result memory, and relevant manager notes/answers.
4. Team cases MUST NOT receive arbitrary editor-specific memories unless the case explicitly includes those editors.
5. Apply configurable size/token budgets per context source.
6. Deduplicate repeated memory.
7. Preserve provenance for every injected memory item.
8. Keep deterministic evidence separate from remembered management context.
9. Serialize context in a stable order.
10. If Honcho retrieval fails, continue with canonical local context and mark the call as memory-degraded.
11. Persist exactly which memory references were injected into each LLM call.

## Required deliverables
Context assembler, scope rules, budget config, provenance model, injection audit, and degraded mode.

## Required tests
Cross-editor isolation, stable ordering, budget enforcement, deduplication, retrieval failure, and provenance completeness.

## Acceptance criteria
Each reasoning case receives only relevant, bounded, auditable memory.

## Explicit non-goals
No new UI. No automatic teaching creation.

## Stop condition
Stop when memory injection is isolated by subject/topic and fully auditable.
