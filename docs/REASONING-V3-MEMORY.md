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

## 2. Tests

`tests/test_reasoning_memory.py` (Phase 10): session naming and Honcho-safe IDs, pseudonymous peers, wrong-session refusal,
raw-data leakage refusal, provenance, the Honcho client's request sequence, caching, per-environment workspace, error mapping and
key redaction, read filtering, settings; with PostgreSQL: mock write/read, duplicate handling, replacement of edited content,
outage → failed → retry, stale content never re-sent, backend bugs isolated, memory off, and immutable log identity.
