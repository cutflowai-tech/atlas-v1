# Atlas V1 product specification

Atlas V1 is an internal Editor Performance Intelligence System. Monday.com is the source of truth and the Editor is the evaluated entity.

**Authority:** [`docs/HANDOFF-V2.md`](docs/HANDOFF-V2.md) (Editor Intelligence MVP handoff, 2026-09-29) overrides the product and spec wording in this file, `AGENTS.md`, `ARCHITECTURE.md`, `CONTRACTS.md` and `docs/ATLAS_V1_RULES.md` wherever they conflict. Management decisions in [`docs/DECISIONS.md`](docs/DECISIONS.md) refine the handoff where it leaves a rule open. Vocabulary is defined in [`GLOSSARY.md`](GLOSSARY.md).

## V1 outcome

For one known Editor, ingest real Monday activity and produce a traceable Editor Profile through this pipeline:

`Monday -> normalized status events -> actor and editor identity -> work cycles -> deterministic metrics -> evidence API -> Editor Profile`

## Deterministic behavior

- Work duration starts on entry to `In Progress` and ends on entry to `Ready For Approval`.
- Deadline performance compares the first `Ready For Approval` timestamp with the Requested ETA in effect at that moment (D19): `delta = ready_for_approval_at − requested_eta`. A negative delta is early, zero is on time, and a positive delta is late. There is no tolerance (D5); if one is ever approved it is a single configured value used everywhere.
- Speed comparisons use only completed work with the same canonical Video Type.
- Waset Co actor attribution comes from the exact status transition, never from the Monday actor or its display name, because the shared `Waset Co` account is used by several people. The transition-to-role rules are versioned; a transition without a rule stays unresolved. AI and fuzzy names may not decide it.
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

- A numeric composite employee score, ranking, leaderboard, or hard-coded company benchmark. An Overall Status is required, but only from approved, versioned, deterministic rules (see `docs/HANDOFF-V2.md` §16).
- Using revisions as an editor penalty.
- AI-generated or AI-corrected metrics.
- Payroll, disciplinary, surveillance, forecasting, or client-scoring features.
- A broad dashboard suite before the one-Editor real-data vertical slice is verified.

The contracts in `CONTRACTS.md` and rules in `docs/ATLAS_V1_RULES.md` are normative for the contract version they describe (1.4.0 is the default; 1.5.0 is the D52 production opt-in and its differences are listed in their own section). Unknown business definitions must remain explicit nulls or exceptions rather than being guessed.
