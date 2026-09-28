# DATA-001 evidence — Monday real-data probe (builder-3)

## Outcome

**Real activity logs were not retrieved. Authorized read access was not available to this builder run.** Instead, this candidate provides a reusable, read-only adapter, tested against a synthetic fixture. The run is ready to execute against real data once access is granted.

## Missing access (exact)

| Channel | State in this run |
|---|---|
| `MONDAY_API_TOKEN` environment variable | Not set. No Monday or Atlas env vars exist in the scoped environment (checked by name only; no values read). |
| claude.ai monday.com MCP connector (`get_board_info`, `get_board_activity`) | Connector present. The tool call was **not permitted** in this session ("permissions … haven't granted it yet"). No retry was attempted. |
| Existing raw snapshot `/Volumes/Zeno/Waset Co Second Brain/raw/monday/2026-07-25` | Blocked by sandbox; only the assigned worktree is readable. Per the task packet, this snapshot has board `5091110326` but no activity logs. |

To run the real probe, one of these is required:
- A Monday API token with `boards:read` scope for board `5091110326`, exported as `MONDAY_API_TOKEN`.
- Read-only grants for the MCP connector.

The following must also be provided, because none of them is guessed:
- The status column id.
- The known Editor's item id(s).
- Optionally, a versioned actor mapping file.

## Adapter

`src/atlas_commander/monday_probe.py`
- `MondayReadOnlyClient`: a GraphQL client. `assert_read_only` rejects any `mutation`/`subscription` operation, and anything that is not a `query`, so no source mutation is possible through it. The transport is injectable for tests. A missing token or an API error raises `MissingAccess` with the exact reason, and the CLI then exits `2` without writing anything.
- `probe`: fetches board columns plus `activity_logs`, filtered to item ids and the status column, with pagination.
- `store_raw`: stores the raw envelope content-addressed (`sha256` in the filename), created with `O_EXCL` and mode `0444`. It refuses any path inside the git checkout and refuses to overwrite differing content.
- `normalize`: builds candidate `NormalizedStatusEvent`s and validates each one against the frozen contract.
  - Raw `event_id`, board id and item id are retained verbatim.
  - `occurred_at` is converted losslessly from Monday's 100 ns tick `created_at`, down to microseconds. The raw tick is kept in the manifest sample.
  - Status labels are accepted only when they exactly match a contract enum value. Any other label becomes an `UNMAPPED_*_STATUS` issue, and no event is emitted.
  - Actors are canonical only when a mapping with a `mapping_version` contains the Monday user id. Otherwise the event gets `unresolved_waset_co` with `actor_id: null` plus an `UNRESOLVED_ACTOR` issue.
- `redact`/manifest: keeps ids, event types, raw timestamps and status label text. Monday user ids become `sha256:` prefixes. Item names, column titles, free-text values and account ids are dropped.
- `drift_report`: covers missing and unexpected activity-log keys and status-data keys, whether the status column exists, and configured or observed labels that are not in the contract. It also lists contract statuses that the board doesn't configure, and counts issues by code.

CLI (real mode, once access exists):

```
PYTHONPATH=src python3 -m atlas_commander.monday_probe --board-id 5091110326 \
  --item-id <editor item id> --status-column-id <column id> --from <iso> --to <iso> \
  --raw-dir "/Volumes/Zeno/Waset Co Second Brain/raw/monday/<date>" --out-dir <redacted output dir> \
  [--actor-mapping <versioned mapping json>]
```

`--from-raw <file>` rebuilds the manifest and drift report from a stored envelope without calling Monday.

## Evidence artifacts (fixture mode — synthetic, not Monday data)

- `fixtures/monday/activity-logs.synthetic.json`: a synthetic envelope that follows the Monday `activity_logs` shape. It is marked `mode: fixture` and carries a `_note`.
- `docs/evidence/DATA-001/manifest.json`: the redacted sample manifest produced by the CLI (`--from-raw`).
- `docs/evidence/DATA-001/drift.json`: the schema drift report. It shows that a `Stuck` label is not in the contract, and that `Approved`/`Delivered`/`Revision` are not configured, for the synthetic board.

## Tests

- `PYTHONPATH=src python3 -m unittest tests.test_monday_probe -v`: **15 tests, OK.** They cover:
  - mutation refusal and query-only traffic;
  - exact missing-access reporting (API and CLI);
  - µs timestamp conversion;
  - raw id and timestamp retention;
  - no guessed actor, status or mapping version;
  - redaction;
  - drift report;
  - immutable raw store outside git;
  - deterministic output.
- `make test`: **pass**. This covers ruff, mypy, unit 11, contract 6, integration 2, e2e 2 and the JSON validity check.
- Note for the integrator: the `Makefile` targets use fixed `-p` patterns, so `test_monday_probe.py` is **not** included in `make test`. The Makefile was left unedited, as outside this task's scope. Its lint and type checks do cover the new files.

## Assumptions

- `unresolved_waset_co` is used for *any* actor that is absent from a supplied versioned mapping, because the contract has no other unresolved value. The raw Monday user id is retained in `actor_monday_id`.
- The Monday API version is pinned to `2025-04`. The `activity_logs` field set is `id event data entity user_id account_id created_at`.

## Contract impact

None. `contracts/normalized-status-event.schema.json` is consumed unchanged. No contract, DAG or unrelated module was edited.
