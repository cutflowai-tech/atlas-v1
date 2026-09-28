# Atlas V1 product specification

Atlas V1 is an internal Editor Performance Intelligence System. Monday.com is the source of truth and the Editor is the evaluated entity.

## V1 outcome

For one known Editor, ingest real Monday activity and produce a traceable Editor Profile through this pipeline:

`Monday -> normalized status events -> actor and editor identity -> work cycles -> deterministic metrics -> evidence API -> Editor Profile`

## Deterministic behavior

- Work duration starts on entry to `In Progress` and ends on entry to `Ready For Approval`.
- Deadline performance compares the `Ready For Approval` timestamp with the Monday `Requested ETA`; it is on time only when approval-ready time is at or before that ETA.
- Speed comparisons use only completed work with the same canonical Video Type.
- Waset Co actor attribution uses the transition actor's canonical Monday person/team ID and a versioned mapping. Missing or ambiguous mappings remain unresolved; AI and fuzzy names may not decide them.
- Revisions are descriptive context only and never subtract from a score.
- Quality is the canonical value of an approved Monday Performance Label.
- Every metric carries Monday board, item, column, event, timestamp, and source-value evidence plus a rule version.
- AI annotations are optional explanations. They are never inputs to facts, metrics, attribution, or quality.

## V1 surfaces

1. Monday ingestion and immutable raw event capture.
2. Normalization, identity, deterministic actor attribution, and exception handling.
3. Work-cycle reconstruction and speed, deadline, and quality metrics.
4. Evidence API and a single Editor Profile.
5. Contract, unit, integration, and end-to-end verification with real-data validation after fixture development.

## Explicitly out of scope

- A composite employee score, ranking, performance verdict, or hard-coded company benchmark.
- Using revisions as an editor penalty.
- AI-generated or AI-corrected metrics.
- Payroll, disciplinary, surveillance, forecasting, or client-scoring features.
- A broad dashboard suite before the one-Editor real-data vertical slice is verified.

The contracts in `CONTRACTS.md` and rules in `docs/ATLAS_V1_RULES.md` are normative. Unknown business definitions must remain explicit nulls or exceptions rather than being guessed.
