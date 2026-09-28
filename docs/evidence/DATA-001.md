# DATA-001 — builder-2 evidence

Candidate implements the authorized fallback: reusable read-only acquisition and real snapshot inspection. **Live activity retrieval and the one-known-Editor evaluation are blocked**, not completed. No fabricated events or metrics were produced.

## Real source and retention

Inspected only Customer Projects board `5091110326` and the source manifest in `/Volumes/Zeno/Waset Co Second Brain/raw/monday/2026-07-25`. The board export is Markdown, not an original API JSON response: 6,044,737 bytes, 959 item records, 37 columns. The source manifest explicitly says activity logs were not requested, rather than denied.

[Redacted sample manifest and machine-readable drift](DATA-001-manifest.json) contain hashes, sizes, column IDs/types, status discrepancies and blockers. Item names, Editor names, emails, links, budgets, update text and person identifiers are excluded. The full board export and source manifest were copied byte-for-byte into `/private/tmp/atlas-data-001-builder-2/<sha256>.raw`, outside git. Board SHA-256: `ce2d38870381fcc8f92ed68f2c3de4babe08c5f9fa2e89e98b1f3bedb428e870`. Source hash was rechecked after acquisition and matched. Original identifiers, timestamp strings and raw values remain unchanged in the retained bytes.

Files use exclusive creation, content addressing, integrity verification on repeated writes, and mode `0400`; the directory is private. This is application-level immutability, not WORM storage. The temporary directory is local evidence and can be removed by OS cleanup; archive it in an approved private evidence store before cleanup if long-term retention is required. No source file was written and no Monday request was sent during this run.

## Exact missing access

No Monday/Waset-named process environment variable was present. Repository integrations contain no Monday client. Inspected Codex MCP configuration server names and environment key names only: no Monday server configured. No callable Monday tool was exposed. Scoped ancestor `.env`, `.env.local`, and `.mcp.json` search found no files. No credential values were printed; unrelated credential stores were not searched.

Needed for live acquisition: an authorized `MONDAY_API_TOKEN` able to read Customer Projects board `5091110326` and its activity logs, plus network access to `https://api.monday.com/v2`. Token permissions and network reachability were not tested because no token was available. Also needed for the task's Editor scope: a verified canonical Editor identity and approved, versioned mapping from that identity to board Editor dropdown label IDs and item membership, plus the desired bounded history interval. None was supplied. Board subscriber IDs and dropdown display names are not identity mappings. No arbitrary Editor was selected.

## Schema drift and normalization blockers

This is a source-to-contract compatibility report, not proof of temporal schema change; no prior approved board schema baseline was supplied.

- `dropdown_mm1emgt8` (Editor Name) is a dropdown. It cannot establish a canonical Monday person ID. `project_owner` is a separate people column and is not assumed to identify the evaluated Editor.
- `project_status` has exact `In Progress` and `Ready For Approval` labels. Other observed labels include `Done`, `Revisions`, `Internal Revisions`, `Sent`, `Ready To Send`, caption stages and blank. These are not silently translated into contract statuses. Contract labels `Backlog`, `Revision`, `Approved`, `Delivered` are not observed verbatim. Full differences appear in the manifest.
- `date` is Requested ETA, type date. No timezone/end-of-day interpretation is inferred and no Client ETA fallback is used.
- `dropdown_mm062ga0` is Video Type. No cross-type cohort or label consolidation is inferred.
- `dropdown_mm3tyvvc` and `dropdown_mm3tyk8g` contain possible quality/context labels. No approved quality mapping was supplied; revisions, bonuses and deductions are not quality scores.
- Item created/updated timestamps and textual updates cannot substitute for activity events. Without transition history there are no evidenced duration or deadline outputs.
- Live board activity `created_at` is documented as a 17-digit timestamp string. The adapter preserves this and the opaque `data` JSON string verbatim. It does not convert it into contract `occurred_at`, resolve shared Waset Co actors, or invent missing status/column/item mappings.

Contract impact: **none**. Frozen `normalized-status-event.schema.json` and `common.schema.json` were read and unchanged; neither has referenced schema dependencies. No normalized events are emitted. Canonical identity resolution and approved versioned mappings remain upstream prerequisites.

## Reusable adapter

`src/atlas_monday/probe.py` contains one fixed GraphQL **query**; callers cannot submit operations. Board scope is fixed. Item IDs, dated API version and timezone-aware interval are explicit. Actor filtering is intentionally absent because it would omit shared-account actions on an Editor's items. Redirects are refused to prevent forwarding authorization. Error messages do not echo credentials or remote bodies.

Responses are retained before JSON/schema validation. GraphQL errors, missing board, invalid shape, duplicate event IDs, and the page cap fail closed. Empty-page termination is reported separately from historical completeness, which remains unproven because of API retention/pagination limits. No source mutations, metric calculation, status mapping or automatic retry occurs. HTTP transport failures expose a generic error; failed HTTP bodies are not retained. Tests use synthetic transport responses, not simulated evidence of real Monday access.

Snapshot inspection:

```sh
PYTHONPATH=src python3 -m atlas_monday.probe --raw-dir /private/tmp/atlas-data-001-builder-2 snapshot '/Volumes/Zeno/Waset Co Second Brain/raw/monday/2026-07-25/boards/customer-projects--5091110326.md'
```

Future live invocation, after credentials and evidenced item scope are supplied (replace the item placeholder; token comes from environment):

```sh
PYTHONPATH=src python3 -m atlas_monday.probe --raw-dir /private/tmp/atlas-data-001-builder-2 activity --api-version 2026-07 --item-id CANONICAL_ITEM_ID --from 2026-07-01T00:00:00Z --to 2026-07-26T00:00:00Z
```

The API query fields, pagination and timestamp shape were checked against [Monday board activity documentation](https://developer.monday.com/api-reference/reference/activity-logs). Live API compatibility remains unverified.

## Validation

- `make monday-probe`: **8 passed**. Covers raw byte preservation including large IDs and 17-digit timestamp strings; no overwrite; read-only permissions; git-tree and symlink rejection; fixed read-only query and no actor filter; pagination; fail-closed errors/drift/duplicates/page caps; missing access before transport; deterministic redaction.
- `make test`: **passed**, including Ruff, mypy (5 source files), 11 unit, 6 contract, 2 integration, 2 E2E and 8 probe tests (**29 total**), plus repository JSON parsing. Initial lint failures were corrected before the successful full run.
- Real snapshot drift output recomputed identically; source and retained SHA-256 matched after inspection. Real activity logs, identity attribution, duration, deadline, speed and quality metrics remain unavailable, explicitly rather than guessed.

Makefile adds `monday-probe` and includes it in `make test`. No frozen contracts, DAG, unrelated modules or source snapshot were edited. No services, merge, or push performed.

## Handoff limitation

Candidate commit could not be created. `git add` and `git commit` both failed with `Operation not permitted` creating `index.lock` under the shared Git metadata path `/Users/ahri/multica_workspaces/.repos/afb42aa3-5c4f-42b5-8bfb-7b4b12553712/github.com+cutflowai-tech+atlas-v1.git/worktrees/builder-2/`. That location is outside this session's writable roots, and approval policy is `never`. Changes remain unstaged in the assigned worktree. No candidate commit SHA exists; current HEAD `a035a2eb7039a71cc758744a7b05d6b1d16a7912` is the pre-existing base, not this implementation. An authorized integrator must commit these files after reviewing them.
