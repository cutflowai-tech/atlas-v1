# DATA-001 — builder-1 evidence

Outcome: reusable read-only adapter implemented; real activity-log probe blocked.
No Monday API request was sent and no source was mutated. This candidate does not
claim completion of the known-Editor real-data acceptance path.

## Access inspected and exact missing inputs

- No environment variable name containing MONDAY or WASET was present. Values were
  never printed. No .env file exists at this worktree root or supplied snapshot
  repository root. Repository source/config/scripts inventory contains no Monday
  integration module.
- Scoped ~/.codex/config.toml MCP configuration lists computer-use and node_repl;
  no Monday server configuration. Available tool metadata contains no Monday tool.
  Unrelated credential stores and sibling candidates were not inspected.
- Missing: authorized Monday API token (adapter reads MONDAY_API_TOKEN) with
  boards:read and visibility of board 5091110326, plus accessible activity history
  for an explicit time window. Actual account permissions/retention cannot be
  diagnosed without that credential. Network reachability was not tested with
  an unauthenticated probe.
- Missing for the known-Editor result: canonical Editor Monday ID and approved
  versioned Editor assignment, status-column/status-label and quality mappings.
  Display names and event actors are not used as substitutes.

## Retained real evidence

Input: /Volumes/Zeno/Waset Co Second Brain/raw/monday/2026-07-25/boards/customer-projects--5091110326.md

Exact 6,044,737-byte export retained at:
/private/tmp/atlas-DATA-001-builder-1/raw/ce2d38870381fcc8f92ed68f2c3de4babe08c5f9fa2e89e98b1f3bedb428e870.raw

SHA-256: ce2d38870381fcc8f92ed68f2c3de4babe08c5f9fa2e89e98b1f3bedb428e870

Storage uses mode 0700 directories and exclusive, content-addressed mode 0400
files outside git. This is application-level immutability, not OS-enforced WORM;
/tmp retention is host-dependent. Original source bytes, including identifiers
and timestamp strings, are unchanged. This is a Markdown export, not an invented
original API payload. No activity logs were available to retain.

See DATA-001-manifest.json (redacted, reproducible inventory) and
DATA-001-drift.md (contract gaps and unmeasured live drift).

## Adapter and deterministic behavior

src/atlas_data/monday_probe.py sends a fixed GraphQL query to the fixed Monday
HTTPS endpoint. No caller-supplied GraphQL, mutations, or redirects are accepted.
An explicit API version, board ID, ordered timezone-aware window and page bound
are required. All returned board events are requested: actor filtering would
incorrectly equate event authorship with Editor assignment. Pagination continues
to an empty page; repeated event IDs, bounds, invalid schemas and API errors fail
closed. Raw bytes are saved before response interpretation. Hash filenames,
field counts and manifests are deterministic for the same responses.

Once access exists, supply MONDAY_API_TOKEN through a secure environment and run:

```sh
PYTHONPATH=src python3 -m atlas_data.monday_probe \
  --board 5091110326 --start 2026-07-24T00:00:00Z \
  --end 2026-07-25T00:00:00Z --api-version 2026-07 \
  --raw-dir /private/tmp/atlas-DATA-001-builder-1/live
```

The example window is an explicit operator choice, not a claim that logs still
exist for those dates. Success prints only a redacted manifest. Transport errors
suppress remote exception details; failed requests are not retried automatically.
Local I/O errors remain operational errors. Rate-limit handling and cross-run
resume are not implemented. The live API path has only mocked transport tests.

## Verification and impact

- Task target: make monday-probe — 4 tests passed.
- make test — passed: Ruff, mypy, 25 tests total (11 unit, 6 contract,
  2 integration, 2 E2E, 4 probe), repository JSON validation.
- Tests cover exact raw bytes including leading-zero IDs and 17-digit timestamps,
  immutable repeated writes, git-tree rejection, fixed read-only query, pagination,
  duplicate/bound failures, redacted transport errors, GraphQL/schema failures.
- Initial lint/typecheck failures were corrected before the passing full run.
- Contract/schema impact: none. Frozen contracts and DAG unchanged; Makefile adds
  the probe test target to the full suite. No normalized events or metric values
  are emitted. Duration, deadline, Video Type cohorts, revisions and quality remain
  unevaluated because their required real event/mapping evidence is absent.

## Commit handoff blocked by sandbox

Both git add and git commit were attempted with the configured identity, but Git
could not create its index.lock in the worktree metadata directory:
/Users/ahri/multica_workspaces/.repos/afb42aa3-5c4f-42b5-8bfb-7b4b12553712/github.com+cutflowai-tech+atlas-v1.git/worktrees/builder-1/index.lock

The sandbox returned Operation not permitted. That directory is outside writable
roots and this session disallows permission escalation. No candidate commit was
created. Existing HEAD is a035a2eb7039a71cc758744a7b05d6b1d16a7912 (base only,
not a deliverable commit). Changes remain in the assigned worktree for handoff.
