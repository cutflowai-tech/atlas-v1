# Atlas Reasoning V3: memory and human context (Phases 10–14)

This document covers the human-context layer of Reasoning V3: Honcho contextual memory (Phase 10), the scoped memory context
assembler (11), manager interpretation notes (12), Atlas questions and management answers (13) and Teach Atlas (14). The
foundation it builds on is [`REASONING-V3.md`](REASONING-V3.md); the phase specifications are in [`REV/`](../REV).

One rule holds everywhere in this layer:

```
PostgreSQL  = canonical application state   (notes, answers, questions, teachings, results, sync log, injection audit)
Honcho      = contextual long-term memory    (copies of selected context, retrievable per scope)
```

Honcho is never the database of truth. Every piece of human context is committed to PostgreSQL first; Honcho receives a copy
afterwards, and a Honcho failure never loses, changes or rolls back the canonical row. Honcho identifiers are never Atlas
identifiers. Human context is never evidence: it never changes a Monday fact, metric, fingerprint, case identity or Change Gate
decision.

## 1. Phase 10: Honcho as contextual memory

### 1.1 Modules

| Module | Role |
|---|---|
| `memory` | Session policy, source taxonomy, `MemoryRecord`, leakage rules (`check_record`), `MemoryBackend` protocol, error classes |
| `honcho_client` | `HonchoClient`: the only module that knows Honcho's API (v3); `backend_from_env` |
| `fake_honcho` | `FakeHoncho`: offline backend for tests (outage and rejection switches, call log) |
| `memory_sync` | `MemorySyncService`: copies committed canonical rows, deduplicates, retires replaced copies, retries |
| `store.memory_log` | SQL for `memory_sync_log` |

### 1.2 Configuration (environment only)

| Variable | Default | Meaning |
|---|---|---|
| `ATLAS_REASONING_MEMORY` | `off` | `on` synchronizes context to Honcho and retrieves memory from it. Off: canonical context only |
| `ATLAS_REASONING_ENVIRONMENT` | — | `development` / `test` / `staging` / `production`; required when memory is on |
| `HONCHO_API_KEY` or `HONCHO_API_KEY_FILE` | — | The Honcho key (set one, never both); required when memory is on |
| `ATLAS_HONCHO_BASE_URL` | `https://api.honcho.dev` | https only (plain http only to 127.0.0.1/localhost/::1) |
| `ATLAS_HONCHO_TIMEOUT_SECONDS` | `10` | Per request, 1–60 |

The key is read only from the environment or a secret file, is excluded from every `repr`, is sent only in the `Authorization`
header and is redacted from every error message. It is never sent to the frontend; no page or fragment of this layer reads it.
CI and the tests never need it (`fake_honcho`, injected HTTP functions).

```bash
PYTHONPATH=src python3 -m atlas_reasoning memory-health --dry-run   # configuration only, no network call
PYTHONPATH=src python3 -m atlas_reasoning memory-health             # get-or-create the environment's workspace
PYTHONPATH=src python3 -m atlas_reasoning memory-sync --limit 100   # re-send pending/failed copies, rebuilt from PostgreSQL
```

### 1.3 Workspace, peers and sessions

- **Workspace:** one per environment, `waset-atlas-<environment>`, so staging or test memory can never reach production reasoning.
- **Peers:** `atlas` (Atlas questions, prior reasoning summaries) and one pseudonymous peer per management author,
  `manager-<16 hex of SHA-256(author)>` (`management` when the author is unknown). Honcho never receives an author's identity.
- **Sessions** (logical keys, stored in `memory_sync_log.session_key`):

| Key | Holds |
|---|---|
| `global:teachings` | company-wide teachings |
| `team:editors` | team-level prior reasoning |
| `editor:<editor_id>` | teachings, answers and prior reasoning about one Editor |
| `video-type:<key>` | the same for one Video Type |
| `workflow:<stage>`, `client:<id>` | teachings with that scope |
| `result:<result_id>` | manager notes, Atlas questions, answers and specific-result teachings of one result |

Honcho IDs allow only `[A-Za-z0-9_-]`, so a logical key maps to `atlas-<kind>-<24 hex of SHA-256(key)>`; the logical key travels
in the session and message metadata.

### 1.4 Source taxonomy and session policy

Every memory item carries its `source_type` (`enums.NoteSource`) and the ID of its canonical row; `check_record` refuses anything
else before a request is made.

| Source type | Canonical row | Allowed sessions |
|---|---|---|
| `manager_interpretation` | `manager_notes` | `result:` |
| `atlas_question` | `atlas_questions` | `result:` |
| `manager_answer` | `atlas_answers` | `result:`, `editor:`, `video-type:` |
| `management_teaching` | `teachings` | `global:teachings`, `editor:`, `video-type:`, `workflow:`, `client:`, `result:` |
| `prior_reasoning_summary` | `reasoning_results` (current version) | `result:`, `editor:`, `video-type:`, `team:editors` |

Message metadata (`MemoryRecord.provenance`): `atlas` (= `atlas-memory-v1`), `source_type`, `source_id`, `session_key`,
`recorded_at`, `content_sha256` and only allow-listed scalar keys (`case_id`, `result_id`, `result_version`, `question_id`,
`revision`, `scope_type`, `scope_id`, `teaching_type`, `validity_mode`, `valid_from`, `valid_until`, `expected_context_type`,
`conflicts_with`).

**Raw-data leakage.** Raw Monday history is never uploaded: no module of this layer reads upstream Atlas or Monday; a memory body is
prose up to 8000 characters (a JSON document is refused); metadata is allow-listed scalars; and a prior reasoning summary is built
from a result's title, management summary and confidence level only, never from its evidence references or Monday IDs.

### 1.5 Synchronization (`memory_sync_log`, migration `0200_memory_sync.sql`)

1. A service commits its canonical row in its own transaction.
2. `MemorySyncService.sync(records)` then, per record, inserts (or finds) the log row keyed by (source type, source ID, session,
   operation, content hash) and locks it (`FOR UPDATE SKIP LOCKED`):
   - already `synced` → `duplicate`, nothing is sent;
   - memory off → `skipped`;
   - backend success → `synced` with the backend's message reference (`external_ref`), then older live copies of the same source
     in the same session are retired (Honcho metadata `atlas_retired: true`, `retired_at` set);
   - backend failure → `failed` with `error_class` (`memory_unavailable`, `memory_rejected`, `internal_error`); the caller gets an
     outcome, never an exception.
3. `retry()` rebuilds the current records of every pending/failed source from PostgreSQL (registered resolvers) and syncs them;
   a log row whose content is no longer current is marked `skipped`, so stale content is never re-sent.
4. `retire_source(source_type, source_id)` retires every live copy of a source (a disabled or archived teaching).

Phases 07–09 call `MemorySyncService.sync_result(result_id)` after committing a result version to copy its management summary to
the result session and its subject session.

## 2. Phase 11: the scoped memory context assembler

`memory_context.MemoryContextAssembler` (migration `0201_memory_injections.sql`) decides what human context and memory one
reasoning call may see.

```python
from atlas_reasoning.honcho_client import backend_from_env
from atlas_reasoning.human_context import context_sources          # Phases 12-14 register their canonical sources here
from atlas_reasoning.memory_context import MemoryContextAssembler, budget_from_env

assembler = MemoryContextAssembler(store, backend_from_env(), sources=context_sources(), budget=budget_from_env())
context = assembler.assemble(case_document)                        # from change_gate.case_for_work
enriched_case = context.apply(case_document)                       # manager_context + memory_context filled; evidence untouched
assembler.record(context, purpose="analyst", request_id=request_id, run_id=..., work_item_id=..., result_id=...)
```

### 2.1 Scope rules

| Case subject | Memory sessions in scope |
|---|---|
| Editor | its results' `result:` sessions, `editor:<subject>`, `video-type:` of its Video Types, `global:teachings` |
| Team | its results, its Video Types, `team:editors`, `global:teachings`; **no** `editor:` session unless the caller names Editors the case includes (`explicit_editor_ids` ⊆ `scope.affected_editor_ids`) |
| Video Type | its results, `video-type:<subject>` (+ affected types), `global:teachings` |
| Workflow stage | its results, `workflow:<stage>`, its Video Types, `global:teachings` |
| Project / data source | its results, its Video Types, `global:teachings` |

An Editor case can never be widened to another Editor (`explicit_editor_ids` outside the case is an error). Sessions outside the
scope are never read.

### 2.2 What is injected

- `manager_context` (canonical): items from the registered `ContextSource`s read from PostgreSQL (notes, answers, teachings).
  Always available; never depends on Honcho.
- `memory_context` (remembered): items read from in-scope sessions, kept only when provably current: the metadata names the
  session it was read from (`memory_wrong_session` otherwise), a live `memory_sync_log` row produced exactly this copy with this
  content hash (`memory_not_canonical`), and the source is still valid (`memory_not_current`: a stale result version, a
  disabled/expired teaching, the analyst's own previous result).
- Deduplicated: one item per canonical source (canonical wins) and per normalized body text (`duplicate`).
- Ordered deterministically: scope (result → this case → Editor → Video Type/workflow/client → team → company), source type
  (teaching, interpretation, answer, prior reasoning, question), newest first, source ID.
- Budgeted (`MemoryBudget`, `budget_from_env`): total 3000 tokens, 500 per item (longer items are cut and marked truncated), 24
  items, per source: teachings 1200, interpretations 800, answers 800, prior reasoning 600, questions 0. Tokens are estimated as
  `ceil(characters / 4)`. Overrides: `ATLAS_REASONING_MEMORY_TOTAL_TOKENS`, `..._ITEM_TOKENS`, `..._MAX_ITEMS`,
  `ATLAS_REASONING_MEMORY_<SOURCE_TYPE>_TOKENS`.
- Every dropped item is counted by reason in `dropped`.

### 2.3 Degraded mode and audit

A backend failure (or bug) during retrieval returns the canonical context with `memory_context.status = degraded` and the error
class as `degraded_reason`; with memory off the status is `not_requested`. `record()` writes one append-only `memory_injections`
row per call: case, result, run, work item, gateway `request_id` (unique), purpose, status, sessions read, budget, every selected
item (position, source type and ID, origin, scope, session, memory reference, content hash, tokens, truncation), drop counts and
the SHA-256 of the serialized context.

## 3. Phase 12: manager interpretation notes

`manager_notes.ManagerNotes` (tables `manager_notes`, `manager_note_revisions` from `0001`; no new migration).

| Operation | Behaviour |
|---|---|
| `create(result_id, body, author=)` | validates the text (`user_text`), commits the note (source `manager_interpretation`, revision 1) and its first revision row, **then** syncs a copy to `result:<result_id>` |
| `update(note_id, body, author=, expected_revision=)` | row-locked optimistic edit: a stale `expected_revision` raises `NoteConflict` (409); an unchanged body writes nothing; each edit appends a revision row; the new copy replaces the old one in memory |
| `get`, `for_result`, `history` | canonical reads (history = every revision with author and time) |

- The note's case is always its result's case (composite foreign key). `author` is the latest editor; the revision rows keep every
  author. Revisions and the note's identity/source columns are immutable (database triggers).
- A Honcho outage is reported in the write's `sync` outcomes and never loses the note; `memory-sync` later sends the *current*
  revision (an outdated failed copy is marked `skipped`).
- `NoteContextSource` gives the assembler the notes on every result of the same case as attributed `manager_context`; a remembered
  copy of an older revision is never injected. A note never enters `current_evidence`, a fingerprint or the evidence tables.

### 3.1 Text safety (`user_text`)

Text is stored as plain text: NFC, `\n` line endings, bidirectional override characters removed, other control characters refused,
bounded length (notes and answers 8000). It is escaped when rendered (`human_context_html`), never altered for display in storage.

### 3.2 Write API (`management_api`) and card fragment (`human_context_html`)

Atlas serves a static site, so the API is a transport-neutral handler (`ManagementAPI.handle(Request) -> Response`). Phase 16 mounts it
in `web_app` behind the authenticating proxy ([`REASONING-V3-DASHBOARD.md`](REASONING-V3-DASHBOARD.md)); production rollout is Phase 20's.

| Concern | Rule |
|---|---|
| Authentication | `Request.actor` is set by the proxy; missing → 401 |
| Authorization | actor (case-insensitive for ASCII identities, exact otherwise) must be in `ATLAS_REASONING_MANAGERS` → 403 |
| CSRF | writes need `Content-Type: application/json` (415), an allowed `Origin` when sent (`ATLAS_REASONING_ALLOWED_ORIGINS`), and `X-Atlas-CSRF` = HMAC-SHA256(`ATLAS_REASONING_CSRF_SECRET[_FILE]`, actor) (403); `GET /api/reasoning/csrf` issues it |
| Input | body ≤ 32 KiB (413); JSON object with only documented fields (`UNKNOWN_FIELD`, `MISSING_FIELD`); text codes `EMPTY`, `TOO_LONG`, `CONTROL_CHARACTERS`, `INVALID_TYPE`; IDs `[A-Za-z0-9_]{1,80}` |
| Audit identity | the author is always the authenticated actor (an `author` field is refused) |
| Responses | JSON, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`; errors are codes, never internals or credentials |

Routes: `GET /csrf`, `GET|POST /results/{result_id}/notes`, `PUT /notes/{note_id}`, `GET /notes/{note_id}/history`.

`human_context_html.note_panel(result_id, notes, csrf_token=)` renders the card's "Manager interpretation" box: every note escaped
and attributed, labelled "Management context, not evidence", `data-source-type="manager_interpretation"`, and a text box posting
to the API. No script, no credentials.

## 4. Phase 13: Atlas questions and management answers

`atlas_questions.AtlasQuestions` (tables `atlas_questions`, `atlas_answers` from `0001`; migration `0202_atlas_questions.sql` adds ask
history, dismissal metadata and the state-transition trigger). Not a chat: only questions a committed result version asked can be
answered.

**From results.** Phases 07–09 call `record_result_questions(result_id, version=None, run_id=...)` after committing a version. Per
question of `questions_for_management` (text, reason, `expected_context_type`):

| Situation | Outcome (`atlas_question_asks.outcome`) |
|---|---|
| answerable from deterministic evidence (how many, which projects were late, the late rate, when delivered, …) | `suppressed_evidence` (no question) |
| same `dedup_key` (normalized text) already open for the case | `repeated`: the open question's `ask_count`, latest result version and run are updated; no duplicate |
| same key answered before | `suppressed_answered`: the answer is reused as context |
| same key dismissed before | `suppressed_dismissed` |
| otherwise | `created`: stored open, then copied to `result:<result_id>` (`atlas_question`, peer `atlas`) |

Re-processing a version is a no-op (`UNIQUE (result_id, result_version, dedup_key)`); the database also allows only one open
question per case and key, so concurrent runs create one question. When the current version no longer asks an open question it
becomes `superseded`. States: `open → answered | dismissed | superseded` only (trigger).

**Answers** (`answer(question_id, body, author=)`, source `manager_answer`): committed first (append-only), the question becomes
`answered`, then copies go to the result session and the case subject's session (`editor:` / `video-type:`), and the question's
own copy is retired. An identical answer (normalized) creates nothing. A different later answer is stored with
`conflicts_with_answer_id` = the previous latest answer: both stay, `has_conflicting_answers` is true, and the context item states
the conflict ("Conflict: management answered differently earlier (...): ..."). Dismissed or superseded questions take no answers;
answered questions cannot be dismissed (`QuestionClosed`, 409).

**Reuse.** `AnswerContextSource` gives the assembler the latest answer of every answered question of the case; a remembered answer
from another case of the same Editor/Video Type is admitted while it is still its question's latest answer.

API: `GET /results/{result_id}/questions`, `GET /questions/{question_id}`, `POST /questions/{question_id}/answers {"body"}`,
`POST /questions/{question_id}/dismiss {"reason"?}`. Fragment: `human_context_html.question_panel` (question, why it matters,
expected context, state, answer history with conflict badges, answer/dismiss controls; all text escaped).

## 5. Phase 14: Teach Atlas

`teach_atlas.TeachAtlas` (tables `teachings`, `teaching_revisions` from `0001`; migration `0203_teach_atlas.sql` adds
`affects_source_data`, status audit columns, the archive/scope/revision guard trigger, no-delete, and `engineering_review_flags`).

| Field | Values |
|---|---|
| scope | `company` (no `scope_id`), `editor`, `video_type`, `workflow`, `client`, `specific_result` (the result must exist) |
| type | `business_rule`, `context`, `correction`, `interpretation`, `temporary_situation` |
| validity | `until_changed` (from creation, no end), `date_range` (`valid_from`..`valid_until`; a date-only end includes that day), `current_period` (the current calendar month, UTC) |
| status | `active`, `disabled`, `archived` (final; stays readable) |

- **Canonical first.** Create/edit/status change commit the teaching and an append-only revision snapshot, then sync. An effective
  teaching (active and `valid_from <= now < valid_until`) has one live copy in its scope's session (`global:teachings`,
  `editor:`, `video-type:`, `workflow:`, `client:`, `result:`); disabling, archiving or a teaching not yet in effect retires
  copies; `retire_expired()` (run by `python -m atlas_reasoning memory-sync`) retires copies whose validity ended.
- **Expiry.** `TeachingContextSource` injects only effective teachings, relevant to the case scope: company always; Editor
  teachings for that Editor's cases (and team cases that explicitly include the Editor); Video Type and workflow teachings when the
  case involves them; specific-result teachings for that result's case. A remembered copy is checked again (effective, relevant,
  same revision), so an expired teaching is never injected even while its copy is still live. Client teachings are stored, synced
  and listed but not injected: cases carry no client dimension yet.
- **Edits** use optimistic concurrency (`TeachingConflict`, 409); the scope is immutable (database trigger) — a teaching for another
  subject is a new teaching. Every change is a new revision.
- **Evidence is never rewritten.** Human-context modules contain no write to any `reasoning_*` table (static test), and a test
  digests every case, evidence, observation, result, version, link and work-item row before and after teaching: unchanged.
- **Corrections** must state `affects_source_data`. When true, an engineering review flag is opened (one open flag per teaching;
  `GET /api/reasoning/review-flags`), and the teaching reaches reasoning labelled: "Management reports that upstream source data may
  be wrong here; engineering is reviewing it. The deterministic evidence has not been changed."

API: `GET /teachings[?status=&scope_type=]`, `POST /teachings`, `PUT /teachings/{id}`, `POST /teachings/{id}/enable|disable|archive`,
`GET /teachings/{id}/history`, `GET /review-flags`. Page: `human_context_html.teach_atlas_page` (form with scope, type, validity and
the data-issue checkbox; list showing source, scope, type, validity, status, author/revision and actions; all text escaped).

## 5a. Integration review fixes (07–14 integration gate)

An independent review before PR #33 was merged found these defects; each is fixed with a regression test:

| Defect | Fix |
|---|---|
| A note whose text looks like JSON was committed, then the memory policy raised, so the API answered 400 and a retry duplicated it | `MemorySyncService.sync` never raises after a canonical commit: a copy the policy refuses is reported `refused` (nothing logged or sent) |
| Re-asserting an earlier answer (A, B, A) returned the first A unchanged, so reasoning kept using B | Only the question's **latest** answer makes a resubmission a repeat; an earlier position re-asserted is a new answer that conflicts with the latest |
| A teaching dated to start later was never copied to memory once in effect | `TeachAtlas.sync_effective()` (run by `memory-sync`) copies every active teaching in effect now; existing copies are duplicates |
| Re-processing an old result version revived a question a later version had superseded | `record_result_questions` does nothing for a version that is no longer current or was already processed; one unusable question text no longer stops the others |
| The Honcho key could follow a redirect (urllib re-sends `Authorization`) | Redirects are never followed (a 3xx is `MemoryRejected`); response bodies are capped at 4 MiB |
| Retired copies (every edit leaves one) could hide older live copies from `read` | `HonchoClient.read` pages past retired copies until `limit` live copies are found (at most 10 pages) |
| A superseded or resolved result's summary was still injected as prior reasoning | `PriorReasoningSource.is_current` refuses superseded and resolved results |
| A remembered copy was accepted on the hash Honcho returned in its metadata | The assembler recomputes the content hash from the returned body and metadata |

Known limitations kept (documented, not defects of the canonical state): `evidence_answerable` is an English-pattern heuristic; teaching
dates and `current_period` are UTC; a failed Honcho retire is only logged (the assembler re-validates every copy, so a stale copy is
never injected); copies logged `skipped` while memory was off are re-sent only when their source is synced again.

## 6. Tests

`tests/test_reasoning_memory.py` (Phase 10): session naming and Honcho-safe IDs, pseudonymous peers, wrong-session refusal,
raw-data leakage refusal, provenance, the Honcho client's request sequence, caching, per-environment workspace, error mapping and
key redaction, read filtering, settings; with PostgreSQL: mock write/read, duplicate handling, replacement of edited content,
outage → failed → retry, stale content never re-sent, backend bugs isolated, memory off, and immutable log identity.

`tests/test_reasoning_memory_context.py` (Phase 11): scope rules (Editor, team with and without explicit Editors, no widening of
an Editor case), stable order under shuffled input, deduplication, budget enforcement and truncation, budget configuration; with
PostgreSQL: cross-Editor isolation (other Editors' sessions are never read), forged and mis-sessioned copies dropped, team-case
isolation, previous-result and stale-version exclusion, degraded mode (outage, rejection, backend bug, memory off), provenance
completeness and the injection audit (append-only, unique request), deterministic serialization, and evidence/identity unchanged.

`tests/test_reasoning_manager_notes.py` (Phase 12): text rules, HTML escaping and labelling; with PostgreSQL: create → persist →
sync, edit history and memory replacement, optimistic conflicts (also under concurrent edits), restart persistence, Honcho outage
then retry of the current revision only, correct-result isolation, notes as context never evidence, stale remembered revisions;
API: create/edit/list/history, actor-only attribution, authentication, authorization, CSRF token bound to the actor, content type,
origin, method, validation and size limits, settings.

`tests/test_reasoning_atlas_questions.py` (Phase 13): dedup keys and the evidence-answerable guard; with PostgreSQL: stored fields
and sync, no duplicate open question across repeated runs and versions, one question under concurrent runs, dismissal (retired copy,
idempotent, no answers, not re-asked), supersession, answer persistence/attribution/sync and idempotence, suppression of answered
questions, state and append-only triggers, conflicting answers preserved and flagged in context, answer reuse for the same Editor
only, answers surviving a Honcho outage; HTML escaping; API answer/dismiss routes.

`tests/test_reasoning_teach_atlas.py` (Phase 14): validity windows and scope sessions, page rendering and escaping; with
PostgreSQL: create → persist → sync, scope isolation (company, Editor, Video Type, specific result, client, team with and without
explicit Editors), expiration and temporary validity (date range, current period, not yet in effect, remembered copies of expired
teachings, `retire_expired`), disable/enable/archive (archive final and auditable; triggers), edit history and conflicts, scope
immutability, corrections and engineering review flags with evidence tables byte-identical, Honcho outage; static check that no
human-context module or migration writes evidence tables; API routes.

CI: all of these run in the existing `make reasoning` step (`tests/test_reasoning_*.py`) against the CI PostgreSQL service. No test
needs Honcho or a Honcho key.
