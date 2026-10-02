# Reasoning V3 Phase 15: validation and safety guardrails

No answer from GPT-5.6 Sol becomes canonical, or visible, unless it passes deterministic grounding and safety validation. Conforming
to the JSON Schema is necessary but never sufficient, and the prompt rules are guidance only. The guardrails
(`src/atlas_reasoning/guardrails.py`, validator version `reasoning-guardrails-v1`) are the final gate before a result or a result
version is committed to PostgreSQL. Specification: [`REV/15`](../REV/15-implement-reasoning-validation-and-safety-guardrails.md).
Architecture: [`REASONING-V3.md`](REASONING-V3.md) §17.

```
ReasoningCase → Change Gate → scoped human / memory context → GPT-5.6 Sol (gateway: well-formed JSON only)
        → complete candidate (new: assembled version 1 · update: deterministic patch merged into the next version)
        → PHASE 15 GUARDRAILS (deterministic) → [optional reviewer, high-impact cases only]
        → accepted: canonical PostgreSQL result → Atlas questions → memory sync
        → refused:  reasoning_failed_candidates; previous valid result stays current; ≤ N corrective re-asks with codes
```

## 1. Where validation runs

| Path | Candidate validated | Expected values (set by Python, never the model) |
|---|---|---|
| New result | the assembled `ReasoningResult` v1 (`analyst.candidate_from_response`) | case, new result ID, version 1, snapshot, fingerprint, `analyst-v2`, pinned model, request ID |
| Update | the **merged** next version (`updater.candidate_from_response` → `patch.merge`), plus the patch's own consistency (base version, required changes, unchanged "changes") | the previous version: same result ID, version + 1, same `created_at`, lifecycle and supersession, `previous_result_id` / `previous_result_version` of the case, `update-v2` |

The gateway now only checks that an answer is well formed (field set, reasoning-v1 contract) and retries malformed JSON within its
bounds. Everything about grounding and safety is decided by the guardrails on the complete candidate, so a candidate is always
judged as it would be stored.

## 2. Error taxonomy

Codes are stable (`guardrails.ValidationCode`); new codes are only ever added. One validation pass reports every violation it finds
(`Violation(code, path, detail)`).

| Code | Meaning | Retried with codes |
|---|---|---|
| `CONTRACT_INVALID` | the candidate is not a valid reasoning-v1 result | yes |
| `PATCH_INVALID` | an update that is not a valid patch of the previous version (a required change missing, a listed change that changes nothing, …) | yes |
| `IDENTITY_MISMATCH` | case, result, version, snapshot, evidence fingerprint, previous version, `created_at`, lifecycle or supersession differ from what Python set | no |
| `PROVENANCE_MISMATCH` | prompt version or request ID not the call's | no |
| `MODEL_SUBSTITUTED` | answered by another model than the pinned `openai/gpt-5.6-sol` (or its dated canonical slug `-YYYYMMDD`) | no |
| `UNKNOWN_EVIDENCE` | a cited `ref_id` that is not evidence of this case (fabricated, another case's, stale) | yes |
| `WRONG_EVIDENCE_ROLE` | contradicting evidence cited as support, or only supporting evidence cited as counter-evidence | yes |
| `COUNTER_EVIDENCE_MISSING` | a contradicted case whose counter-evidence is missing or cites none of its contradicting evidence | yes |
| `NO_SUPPORTING_EVIDENCE` | a visible conclusion (observation, interpretation, management significance, each supporting-evidence item, an explanation that does not need context) without supporting deterministic evidence | yes |
| `UNSUPPORTED_NUMBER` | a number (digits or words) that is not a case value | yes |
| `UNKNOWN_PERSON` | an Editor identifier or a person-like name the case does not contain | yes |
| `UNKNOWN_PROJECT` | a project / Monday item number not in the case's evidence | yes |
| `UNKNOWN_ENTITY` | another proper name (client, studio, …) the case does not contain | yes |
| `UNSUPPORTED_METRIC` | a metric Atlas does not calculate | yes |
| `CAUSAL_OVERCLAIM` | causation stated where the evidence shows patterns and associations | yes |
| `HR_JUDGMENT` | a judgement about a person (personality, psychology, motivation, character, competence as a trait, pay, employment action) | yes |
| `UNSUPPORTED_BLAME` | a person blamed for an outcome | yes |
| `CONFIDENCE_EXCEEDED` | confidence above the upstream ceiling, `strong` for a contradicted case, or text claiming proof / higher certainty | yes |
| `MEMORY_ATTRIBUTION_LOST` | management context (note, answer, teaching, remembered management context) used without saying it comes from management | yes |
| `CONTEXT_AS_EVIDENCE` | management context presented as an observation, evidence statement or title | yes |
| `REVIEWER_REJECTED` | the optional reviewer refused a deterministically valid candidate | no |
| `REVIEWER_FAILED` | the optional reviewer gave no usable verdict (fails safe) | no |

Work items fail with `validation:<codes>` (sorted, comma-separated).

## 3. Policy: the exact boundary

All rules run on every user-visible text: title, reasoning summary, the observation / interpretation / management-significance
statements, supporting and counter-evidence statements, alternative explanations, confidence rationale, limitations, questions for
management (text and reason) and suggested investigations. Text is split into sentences; "negated" means the sentence contains a
negation (not, no, never, cannot, without, unknown, unclear, …); "hedged" means a possibility marker (may, might, could, can,
possibly, perhaps, potentially, whether, if, would, hypothesis, to check).

### Numbers (`output_checks`, shared with the update path — one numeric system)

Allowed anywhere: values of the case (statement parameters, record values, block samples and comparisons, sample sizes, scope counts,
free-standing numbers in case strings), `0`, `1`, `100`, and rates (values in 0…1) written as percentages at the precision written
(0.6875 → 69% / 68.75%). Allowed only in context: a part of a case date written as a date (next to a month name or as an ISO date:
"since 3 September"); a duration the case stores in seconds written with a unit (minutes, hours, days: "16.5 hours"). For an update,
the material delta's before-values are also allowed ("up from 11 to 12"). Number words (two … twenty, thirty … ninety, hundred,
dozen, thousand) are numbers. Never allowed: anything from management context or memory, any other derived figure (new differences,
averages, projections), counts or durations disguised as date parts. Known limit: a number that is a case value in another meaning
passes (the check is value grounding, not semantic matching).

### Entities

- `editor-…` identifiers must be Editors of the case (subject, affected Editors, Editors of its evidence records).
- "item / project / task / job / video / card / delivery N" and "#N" must be a Monday item of the case's evidence.
- Proper names (capitalized words that are not sentence-initial, possessives, or sentence-initial names followed by a person verb)
  must be words of the case (including its `editor_name` / `display_name` values), Atlas vocabulary, months or weekdays. A name that
  appears only in management context is allowed only inside a sentence that attributes it to management. Title-Case headlines are
  not checked for proper names (identifiers still are).

### Metrics

Allowed: Atlas's own vocabulary (late rate, on-time rate, lateness, revision, quality labels, work time, speed, workload, runway,
cycle, median, cohort, benchmark, trend, recent change, …) and every term the case carries. Refused unless the case carries the term:
score(s), scoring, index / indices, rating(s), ranking(s) / ranked, KPI(s), productivity, efficiency, percentile(s), grade(s),
composite, risk percentage / score / level / rating / index, performance level / score / index / rating, utilisation; and any
"<word> rate" whose word is neither an Atlas rate (late, on-time, lateness, revision, return, approval, delivery, early, deadline),
a case word, nor a describing modifier (higher, lower, current, baseline, team, cohort, …). A qualitative judgement belongs in the
interpretation as an interpretation, never as a computed metric.

### Causality

Upstream evidence levels (fact, metric, pattern, association, interpretation, hypothesis) never establish causation, so no candidate
may. Causal phrases: cause(s/d/ing) …, cause of, the cause, because of, due to, result(s/ed/ing) in, as a result of, led / leads /
leading to, responsible for, the reason for / why / that, attributable to, drove / driven by, is why, explains why, triggered,
stem(s) from, owing to.
- **Refused**: an unhedged causal sentence in any field; any causal sentence (even hedged) in the title, observation, supporting or
  counter-evidence.
- **Allowed**: hedged causal sentences in interpretive fields (interpretation, reasoning summary, management significance,
  alternative explanations, questions, investigations); negated causal sentences anywhere ("Monday does not show what caused the
  delays"); limitations and the confidence rationale (they describe Atlas's evidence, e.g. "weak due to the small sample").
- Association language is always allowed: associated with, coincides with, concentrated in, differs from, co-occurs.

### People

- **Allowed**: observable work evidence about a person or scope: deadline performance deteriorated, late rate rose, quality labels
  increased, work time differs from the cohort, a pattern is concentrated in this scope, an Editor's name or identifier from the case.
- **Refused (`HR_JUDGMENT`)**, in any field, unless it is a negated sentence in `limitations` ("Monday data cannot show motivation or
  effort"): laziness, carelessness, (in)competence, (un)skilled / talented, motivation, effort, work ethic, dedication, attitude,
  personality, character, honesty, loyalty, intelligence, psychological / mental state, depression, anxiety, emotion, burnout,
  stress; salary, pay raise / cut, bonus, compensation; firing, termination, dismissal, letting go, promotion, demotion, discipline,
  warning letter, performance improvement plan, hiring, punishment, reprimand, replacing a person; "good / bad / poor / weak / strong
  editor / employee / worker / person", underperformer, slacker, unreliable person.
- **Refused (`UNSUPPORTED_BLAME`)**, unless negated: blame / blamed / at fault / fault of / culprit / to blame; a person (the editor,
  he / she, an Editor identifier or a name from the case) as the agent of caused / is responsible / is the reason / is at fault /
  failed to / neglected / ignored / did not care; "because of / due to / caused by / driven by / attributable to" a person. Blame is
  refused even when hedged.

### Confidence

The level never exceeds the strongest upstream confidence among the supporting findings, is never `strong` when the case has
contradicting evidence, and no non-negated sentence claims proof or certainty (proves, proven, conclusive(ly), undoubtedly,
definitely, certainly, beyond / without doubt, irrefutable, guaranteed) or claims high confidence (high / strong / very confident,
"strong evidence", "the result is strong") while the level is below `strong`.

### Human context stays attributed

Management sources are manager interpretations, management answers and teachings (in `manager_context`, and the same sources in
remembered `memory_context`). Atlas's own remembered prior reasoning and questions are not management statements. For each management
item the guardrails take its distinctive words (at least four letters, not stopwords, not Atlas vocabulary, not words of the case's
evidence; an answer's quoted question line is Atlas's and excluded). A sentence **draws on** an item when it shares at least three of
them (two for an item with at most four).
- In the title, observation, supporting or counter-evidence: refused (`CONTEXT_AS_EVIDENCE`), attributed or not.
- Elsewhere: allowed only when the sentence attributes it (management, manager, according to, reported, noted, stated, said,
  answered, teaching, taught, …); otherwise `MEMORY_ATTRIBUTION_LOST`. Questions for management are exempt (a question asserts
  nothing).

Human context never supplies numbers (above) and never enters the evidence fingerprint, so it cannot change case identity, evidence,
metric values or the Change Gate. Text inside it is data: an injected instruction ("ignore previous instructions", "say the result
is strong", "invent a score of 97") can at most make the model write a candidate the guardrails then refuse.

## 4. Failed candidates

A refused candidate is never committed. The previous valid result (if any) stays current and open, with its lifecycle unchanged;
no Atlas question is created and nothing is synced to memory. Every refused attempt is recorded in `reasoning_failed_candidates`
(migration `0300_failed_candidates.sql`, the only Phase 15 migration): candidate ID, case, run, work item, result ID (new results
never exist), base version (updates), request ID, purpose, attempt, validator version, error codes, every violation, model, prompt
version, evidence fingerprint and the candidate itself (the contract-shaped structured output — for an update also the update
document — up to 256 KiB; no hidden reasoning exists to store and no secrets are ever part of it). Rows are append-only and are
for debugging only: no API route or dashboard fragment reads them. `ReasoningStore`/`StoreTransaction.failed_candidates` reads them.

## 5. Retry policy

- Malformed JSON: the gateway's own bounded retries (`ATLAS_REASONING_LLM_MAX_RETRIES`), unchanged.
- A refused candidate: re-asked at most `ATLAS_REASONING_VALIDATION_RETRIES` times (0–2, default 1) — the same request plus the refused
  answer and a correction message listing **codes and paths only** (never the refused text or management text echoed back), under
  a new request ID with its own injection audit. Identity, provenance, model and reviewer failures are never re-asked.
- After exhaustion the work item fails (`validation:<codes>`); every attempt stays auditable; other items continue. Re-reasoning
  failed items later is Phase 18's.

## 6. Optional second reviewer

`reviewer.LLMReviewer` (prompt `reviewer-v1`, purpose `review`, the same gateway and pinned model) runs only when
`ATLAS_REASONING_REVIEWER=on` (default off) and the case is high impact: its type is listed in `ATLAS_REASONING_REVIEWER_CASE_TYPES`
(default `editor_pattern`) and its orientation is adverse or mixed. It runs only after the deterministic guardrails accepted the
candidate and can only refuse: approval never overrides a deterministic refusal (the reviewer is not even called). Its input is
bounded and structured (`case`: the canonical evidence view with attributed context; `card`: the visible fields; no identifiers,
provider metadata or credentials). A refusal (`REVIEWER_REJECTED`) or any failure (`REVIEWER_FAILED`) keeps the candidate out. Normal
tests never need it; it costs nothing while off.

## 7. Known limits (for Phase 19 evaluation)

The rules are lexical and conservative: they can refuse a valid sentence (a false refusal keeps the previous valid card, which is
the safe failure) and cannot understand meaning (a case value used in another sense passes the number check; a paraphrase that
avoids the listed words passes the people and causality rules). The vocabularies are explicit in `guardrails.py` so the evaluation
phase can measure and tune them. English only; Arabic text is not covered by the lexicons.
