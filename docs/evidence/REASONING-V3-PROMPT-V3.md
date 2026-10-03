# Reasoning V3 — analyst-v3 / update-v3 (guardrail wording)

**Scope.** This change is to the prompt text only. The validator (`reasoning-guardrails-v1`), the evidence, the canonical case and the
contracts are unchanged.

## 1. What the live runs showed

The first Stage 1 shadow runs on production used `analyst-v2` / `update-v2`. The validator refused the first answer in most cases:

| Run | Input | Cases | Refused on first pass | Accepted in the end |
|---|---|---|---|---|
| Baseline (10 calls) | analyst-input-v1 | 6 | 6/6 | 2 |
| Smoke (12 calls) | analyst-input-v2 | 8 | 6/8 | 4 |

There were 16 refused attempts in total. Most refusals came from exact wording the validator checks but the v2 prompt never stated.
The violation counts (code, path, detail), and the terms behind them:

| Code | Count | Terms that triggered it |
|---|---|---|
| `UNSUPPORTED_METRIC` | 14 | "historical rate", "recorded rate", "deadline-miss rate" (only Atlas's own rates are allowed) |
| `WRONG_EVIDENCE_ROLE` | 10 | records of a contradicting finding cited as support. A record is contradicting by its role **or** by its finding |
| `UNSUPPORTED_NUMBER` | 10 | number words such as "two" where the case carries no 2 |
| `CAUSAL_OVERCLAIM` | 9 | causal wording in factual fields, or unhedged elsewhere |
| `NO_SUPPORTING_EVIDENCE` | 6 | a conclusion citing only contradicting records |
| `HR_JUDGMENT` | 6 | "effort" and similar words, including in limitations |
| `UNKNOWN_PERSON` | 6 | "editor-specific", "editor-level" (they read as Editor IDs) |
| `CONFIDENCE_EXCEEDED` | 5 | "confirm (whether)", "clearly" below `strong` |
| `UNKNOWN_PROJECT` | 3 | a number after "project" / "item" that is not a Monday item of the case |
| `UNKNOWN_ENTITY` | 2 | a capitalized verb starting an investigation ("Compare projects …") |

Corrective retries carry only the codes (Phase 15 design), so the model often repeated the same wording.

## 2. The change

`analyst-v3` and `update-v3` are `analyst-v2` and `update-v2` unchanged, plus one shared section, **Wording Atlas checks
automatically**. For each rule above, the section states the exact rule and the safe wording to use instead:

- the evidence-role definition;
- digits only;
- Editor IDs only, and "for each Editor";
- "Management could …" to start investigations;
- Atlas's own rate names;
- the causal, HR and certainty word lists, with association and hedge wording;
- "check whether" instead of "confirm whether".

The validator lists are not changed.

`tests/test_reasoning_prompt_wording.py` pins both sides against the unchanged validator:
- each live refusal is still refused;
- each wording v3 recommends is accepted;
- the prompt names every allowed rate and representative terms of each validator list (a drift guard);
- the section is identical in both prompts.

## 3. Phase 19 offline evaluation

`evaluate run` (offline, disposable `…_test` database) returns `PASS`, exit 0, no failures, with `report_sha256`
`67dabca2a4d3885d7d7f6eae14651cc003bbd6caac094f0062aca926e2ba6c59`.

A deep diff against the previously approved report (`3b8e9781…a44a`) differs only in `versions.analyst_prompt` (`analyst-v2` →
`analyst-v3`) and `versions.update_prompt` (`update-v2` → `update-v3`). Every metric, threshold verdict and coverage value is
identical. `APPROVED_PHASE19_REPORT_SHA256` is re-established to the new digest in `tests/test_reasoning_phase20_reconciliation.py`.

The offline model is deterministic, so this evaluation cannot measure live model quality. A bounded live smoke of 3–5 cases on
production does that before any larger run.
