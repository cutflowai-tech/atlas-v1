# Atlas Reasoning V3 — Phase 08: Implement Update-Only Reasoning and Patch Merge

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
Update existing results without regenerating unrelated content.

## Scope
Updated cases only. GPT returns a patch; Python performs the merge.

## Required implementation
1. Create a separate versioned update prompt.
2. Input MUST include previous canonical result, exact deterministic evidence delta, current evidence, previous fingerprint, and new fingerprint.
3. Require ReasoningUpdate output.
4. The model MUST list changed fields, preserved fields, and change rationale.
5. Implement the patch merger in Python.
6. Protect immutable fields such as case identity, result identity, creation time, and historical evidence links.
7. Create a new result version after each accepted material patch.
8. If no material semantic change is required, preserve the previous result exactly and record a no-op review.
9. Preserve exact previous wording for untouched fields.
10. Persist before/after diffs.

## Required deliverables
Update prompt, ReasoningUpdate handler, deterministic merger, version creation, diff history, and no-op path.

## Required tests
One-field update isolation, immutable-field protection, invalid path rejection, no-op byte preservation, version increment, and failed patch rollback.

## Acceptance criteria
A small evidence change cannot rewrite the entire card.

## Explicit non-goals
No lifecycle resolution. No Honcho. No executive summary.

## Stop condition
Stop when existing cards update surgically and remain historically recoverable.
