# Reasoning V3 — Rollout Controls (Phase 20-A)

`REV/20` #1, #2, #3 (as an entry-point refusal), #10 and #11. This phase adds the **repository-side application controls** that a staged
rollout needs. It decides which Reasoning V3 capabilities a process runs and shows.

It changes no production topology and deploys nothing. It enables no stage anywhere and touches no security control.

- Deployment artifacts and operating procedures belong to Phase 20-B: runbooks, backup/restore and `deploy/production/**`.
- Every production move (stage changes, deployment, credentials, access) needs separate explicit approval.

Base: Phase 19 closure `74c015f59498484b7d04a7b35ee903361062d7df`. There is no migration (0800–0849 is unused).

## 1. Modules

| Module | Role |
|---|---|
| `src/atlas_reasoning/rollout.py` | The validated capability model (`RolloutConfig`), the six stages (`STAGES`), `stage_of`, `require_execution`. |
| `src/atlas_reasoning/release_metadata.py` | Deterministic release metadata (`release_metadata`) and release eligibility (`eligibility`). |
| `src/atlas_reasoning/web_app.py` | Rollout gating before the existing routing. Presentation inputs for the rollout banner, human context and the executive lead. |
| `src/atlas_reasoning/dashboard_html.py`, `dashboard_i18n.py` | The rollout banner, the disabled human-context notice and the hidden Teach Atlas link (en/ar). |
| `src/atlas_reasoning/__main__.py` | `gate` and `reason` honour the execution flag. New commands: `rollout`, `release-metadata`, `release-eligibility`. |
| `tests/test_reasoning_rollout.py` | The Phase 20-A tests. |

## 2. The capability model

| Variable | Default | Effective capability |
|---|---|---|
| `ATLAS_REASONING_V3` | off | Master switch (Phase 01). When off, every capability below is off. |
| `ATLAS_REASONING_EXECUTION` | on | Reasoning V3 processing may run: the Change Gate (`gate`), reasoning and executive synthesis (`reason`). |
| `ATLAS_REASONING_AUDIENCE` | `none` | Who the reasoning surface is presented to. `none` is shadow: nothing is served. `internal` is internal review. `management` is beta, or primary. |
| `ATLAS_REASONING_CARDS_PRIMARY` | off | Reasoning-first cards are the primary management card experience. |
| `ATLAS_REASONING_HUMAN_CONTEXT` | off | Notes, Atlas Question answers and Teach Atlas: UI and the whole management API. |
| `ATLAS_REASONING_EXECUTIVE_HOME` | off | The ExecutiveBrief leads the reasoning home. |
| `ATLAS_REASONING_MEMORY` | off | Honcho memory (Phase 10). Unchanged; it is listed here because it is independent of the stage. |

**`ATLAS_REASONING_EXECUTION`:** setting it off is the processing kill switch. It never hides or deletes stored results.

**Validation.** Every user-visible capability defaults off, so `ATLAS_REASONING_V3=on` alone is the shadow stage. Unknown values, and
these three genuine dependencies, are configuration errors (`RolloutError`, exit 2):

- `CARDS_PRIMARY` needs `AUDIENCE=management`.
- `EXECUTIVE_HOME` needs `AUDIENCE=management` and `CARDS_PRIMARY` (reconciliation, review L-3: an executive home over beta cards
  would contradict the beta banner).
- `HUMAN_CONTEXT` needs `AUDIENCE` set to `internal` or `management`.

Validation runs even with the master switch off. A capability is never enabled implicitly: a credential, a database URL or the memory
flag turns nothing on. Viewing does not depend on execution, so stored results stay readable with processing paused.

**Stages** (`python -m atlas_reasoning rollout --stages` prints each stage's exact variables):

| # | Stage | Execution | Audience | Cards primary | Human context | Executive home | Primary surface |
|---|---|---|---|---|---|---|---|
| 0 | `off` | — | — | — | — | — | deterministic dashboard |
| 1 | `shadow` | on | none | off | off | off | deterministic dashboard |
| 2 | `internal_review` | on | internal | off | off | off | deterministic dashboard |
| 3 | `management_beta` | on | management | off | off | off | deterministic dashboard |
| 4 | `cards_primary` | on | management | on | off | off | reasoning cards |
| 5 | `human_context` | on | management | on | on | off | reasoning cards |
| 6 | `executive_home` | on | management | on | on | on | executive brief |

Any other valid combination reports as `custom`, for example a stage with `EXECUTION=off` during a provider incident.

`python -m atlas_reasoning rollout` prints the effective, content-free state.

## 3. What each capability does in the application

- **Off.** `create_app` refuses to start (`ReasoningDisabled`), exactly as before Phase 20.
- **Shadow.** Every route of the reasoning web app returns a plain `404 Not Found`: pages, assets, the read API and the
  management API, for any actor. The response is indistinguishable from a route that does not exist and gives no authentication
  hint. Processing (`gate`, `reason`) runs if `EXECUTION` is on. All Phase 15–19 safeguards apply unchanged, because the rollout only
  gates entry points. Nothing in the engine, guardrails or store reads it, and a test enforces this.
- **Internal review.** Pages are served, and each carries an "Internal review build" banner with a link to the deterministic dashboard.
  The read API is served. Human context is off unless enabled; the card shows a "not enabled yet" notice, Teach Atlas is hidden
  and returns 404, and the management API returns 404.
- **Management beta.** Pages carry a "Beta" banner. The deterministic Atlas dashboard is stated and linked as the primary view.
- **Cards primary.** No banner. `primary_surface = reasoning_cards`.
- **Human context.** The management API and Teach Atlas are served, with every existing control: allow-list, CSRF, Origin,
  content-type and bounded bodies.
  - Turning it off hides notes, answers and Teach Atlas everywhere. The card shows a notice and does not read them. The read API
    returns `human_context: {"available": false, "disabled": true}` with no notes or questions. Both the management API and the
    Teach Atlas page return 404.
  - Recorded notes, answers and teachings stay in PostgreSQL and reappear when it is turned back on.
- **Executive home.** The persisted ExecutiveBrief leads the home page (read only, as in Phase 17). Off hides it. Every brief,
  version and synthesis run stays.

**Primary surface.** `primary_surface` (`deterministic_dashboard` / `reasoning_cards` / `executive_brief`) is what the configuration
asks the management entry point to be. Routing management to it is the operator's proxy configuration. That belongs to Phase 20-B
and is a separately approved production change; this phase routes nothing.

**Security is unchanged and is checked inside the gate.** The rollout check runs first and can only refuse (404). When a capability
is on, the request goes through the unchanged Phase 16 path:

- proxy-authenticated actor and manager allow-list (401/403);
- CSRF;
- Origin;
- content type;
- CSP and security headers.

The Phase 16/17 security tests run unchanged. `ReasoningWebApp` constructed directly without a rollout keeps the full Phase 16/17
composition, which those tests use. `create_app`, the production path, always passes the validated configuration and refuses an
invalid one.

**Audience is presentation, not access control.** Who can reach the surface is still decided by the authenticating proxy and
`ATLAS_REASONING_MANAGERS`. Restricting stage 2 to internal reviewers means setting that allow-list and the proxy accordingly. That is
an access change: an operator step, separately approved, with no code change.

## 4. Rollback

Moving between stages means changing these variables and restarting the reasoning processes. Nothing in the application deletes,
rewrites or migrates canonical state on a change of capability. The tests prove it with a per-table row count and content hash of
every `atlas_reasoning` table. That state includes results, history, briefs, notes, answers, teachings, the audit trail, `llm_calls`
and the memory log. It is identical across a full stage 6 → 0 → 6 walk. Byte-for-byte return of the presentation is tested for the beta home and the executive lead.

Rollback order (most visible first):

`EXECUTIVE_HOME=off` → `HUMAN_CONTEXT=off` → `CARDS_PRIMARY=off` → `AUDIENCE=internal` or `none` → `EXECUTION=off` → `ATLAS_REASONING_V3=off`

Any single step can also be taken alone, provided the combination stays valid.

## 5. Degraded operation

The rollout is independent of provider and memory health:

- **Provider outage, partial run, open breaker or exhausted budget:** the Phase 18 statuses apply, and the last accepted cards stay
  served.
- **Honcho outage:** the run is degraded and the cards stay served.
- **`EXECUTION=off`:** no processing, and the stored results stay readable.

Provider and memory failures never become deterministic-data failures. The deterministic site does not depend on Reasoning V3 at
all: `atlas_commander` and `atlas_sync` never import `atlas_reasoning` or read these variables.

## 6. Legacy preservation

The deterministic Atlas site is byte-identical at every stage. That covers the Intelligence V2 technical views, the dashboards and
the evidence, and a test builds the showcase site at stages 0, 1 and 6. Every visible reasoning page keeps its link to the
deterministic dashboard. Removing legacy views is out of scope until management explicitly approves it (REV/20 #10).

## 7. Release metadata (`python -m atlas_reasoning release-metadata [--commit SHA]`)

Fields are derived from code and validated configuration, never typed in:

| Field | Source |
|---|---|
| `commit` | 40 hex, from `--commit` or the checkout's HEAD. Missing means the metadata is incomplete. |
| `reasoning_package` | Package version |
| `reasoning_contract` | Reasoning contract version |
| `executive_contract` | ExecutiveBrief contract version |
| `model`, `model_override`, `pinned_model` | The effective model and whether it is overridden |
| `analyst_prompt`, `update_prompt`, `executive_prompt`, `reviewer_prompt` | Prompt versions |
| `guardrails_validator`, `executive_validator` | Validator versions |
| `evaluation_schema`, `golden_fixture_digest`, `release_thresholds` | Phase 19 identity |
| `latest_migration`, `migrations`, `migrations_sha256` | The migrations directory |
| `rollout_version`, `rollout` | The effective state |
| `software_versions` | Exactly the versions the Phase 19 report records |

The output is deterministic: sorted, with no timestamp. It never contains a key, password, token, URL or path, and a test asserts
this on both values and field names. Exit 1 when incomplete.

`--commit`, if given, sets the release commit. Otherwise the commit is the source checkout's HEAD. It is left empty, which makes the
metadata incomplete, in three cases: outside a git checkout, in a repository that is not this package's own, or when the checkout has
uncommitted changes.

**Binding (reconciliation, review M-2).**

| Field | What it hashes |
|---|---|
| `migrations_sha256` | The migration file **names** only |
| `migrations_content_sha256` | Version, name and SQL checksum of every migration. This is the checksum `schema_migrations` records, so the gate cross-checks it against a migrated database through Phase 20-B's restore-drill reader |
| `prompts_content_sha256` | The sha256 of each prompt text (analyst, update, executive and reviewer) |

The Phase 19 runner JSON carries no commit. It is bound to the release through the report's versions, golden digest and thresholds,
and through this metadata for the commit. Keeping the run JSON, the metadata output and the release record together is the
operator's documented binding (Phase 20-B release record and RECOVERY §2.4).

## 8. Release eligibility (`python -m atlas_reasoning release-eligibility --evaluation RUN.json [--commit SHA]`)

The input to Phase 20 verification. A release is eligible only when all of these hold:

1. The file is a Phase 19 runner result (`evaluate run --output`) whose code and result are `PASS`.
2. Its embedded report matches its `report_sha256`. This is a checksum: it detects corruption or truncation, but it does not
   authenticate the file. Keep the run JSON with the release record.
3. The report is a release-conformant PASS with no missing coverage, and its own stored threshold verdicts all pass with no
   failures. Eligibility reads booleans only.
4. Its threshold version, golden fixture digest and software versions equal this release's metadata. The evaluation was of this
   software.
5. The metadata is complete, and the release runs the pinned model; an overridden model is never eligible.
6. The metadata describes the current, valid rollout configuration.

Phase 19 stays the evaluation authority. Eligibility never recomputes a metric or reads a threshold value (a test checks this).

Exit 0 only when eligible. The output lists every failed condition, the evaluation `mode` and the `outstanding` items. Eligibility
is a repository-side input, not release approval. Final approval still needs:

- a live-model Phase 19 run (operator-approved and budgeted);
- a completed human management review bound to the evaluation report;
- explicit approval of the stage, the deployment and any access change.

The version binding covers the Phase 19 `software_versions`. The executive and reviewer prompt, validator and contract versions are
recorded in the metadata but are not part of Phase 19's evaluated set.

## 8a. Actual release readiness (`python -m atlas_reasoning release-readiness`)

PM decision: **repository eligibility is not release readiness.** `release_readiness` reports `actual_release_ready=true` only when all
of these hold:

1. The release is repository-eligible (§8).
2. A **live-provider** Phase 19 evaluation (mode `live`) is itself eligible for this software.
3. A completed human management review (`evaluate review-validate`) is bound to that live report, with no item rated `fails`.
4. An explicit `reasoning-release-approval-v1` record names the approver, the time, a stage (1–6), this release's commit and the live
   report's sha256.

Anything missing, invalid or unbound is listed, and the result is false. **`rollout_authorized` is always false:** no code path grants
it. Exit 0 only when actually ready.

The repository never contains live evidence or approvals, so at repository-prep time the result is `actual_release_ready=false`,
`rollout_authorized=false`.

## 8b. Phase 20 reconciliation gates (`tests/test_reasoning_phase20_reconciliation.py`)

These are blocking, automatic tests on real Phase 20-A code and real Phase 20-B artifacts, with no mocks.

| Gate | What it checks |
|---|---|
| `P20A_RELEASE_METADATA_COMPLETE` | The metadata is complete for the checkout's commit. Its content hashes match the prompt files and the migrations a migrated database records. Phase 20-B's backup release record accepts its identifiers. |
| `P20A_ROLLOUT_STAGE_MATCH` | Every stage (0–6), passed through Phase 20-B's overlay `environment:` allow-list under Compose's interpolation rules, arrives as exactly that stage. The env template is stage 0, a blank kill switch stays off, the rollout plan's six stages are in order, and `rollout --stages` agrees. |
| `P20A_REPOSITORY_ELIGIBILITY_CONTRACT` | The real offline Phase 19 release evaluation of the tree (every golden case) reproduces the approved Phase 19 report sha256 (`3b8e9781…a44a`, pinned), and `release-eligibility` accepts it. |
| Fail-closed readiness | Without live and/or human evidence, `actual_release_ready=false` and `rollout_authorized=false`, both in `release_readiness` and in Phase 20-B's `release_checklist`. |

## 9. Handoff to Phase 20-B (interfaces, no files touched)

- **Variables and stages:** §2 above, and `python -m atlas_reasoning rollout --stages` as machine-readable JSON. Runbook stage changes
  and rollbacks should use exactly these.
- **State check:** `python -m atlas_reasoning rollout` (exit 2 on an invalid configuration). Run it before restarting with a new stage.
- **Release gate:** `release-metadata`, `release-eligibility` and `release-readiness`.
- **Primary-surface routing:** `primary_surface`, plus the proxy and allow-list per audience. These are proposals for Phase 20-B's
  deployment documents and need separate approval.
- **Processing kill switch:** `ATLAS_REASONING_EXECUTION=off`; `gate` and `reason` exit 2 with `ExecutionDisabled`.

## 10. Known limitations

- The audience flag does not restrict access by itself (see §3); audience separation is the proxy's and the allow-list's.
- A capability change takes effect when the process restarts. There is no live toggle, by design: the configuration is validated
  once at start.
- Release metadata reads the commit from git when `--commit` is absent. In an image without git, or in a dirty checkout, pass
  `--commit` or the metadata is incomplete.
- `ReasoningWebApp` constructed directly without a rollout keeps the full Phase 16/17 composition. That keeps the Phase 16/17
  security tests unchanged. Only `create_app`, the production path, is configuration-driven, and it always passes the validated
  rollout.

## 11. Self-review (independent adversarial pass)

There were no Critical or High findings. These were fixed with regression tests:

- **M1:** the read API returned notes and answers while human context was off. It now omits them, and the card no longer reads
  them.
- **M2:** eligibility ignored an overridden model and an offline-only run. It now refuses an overridden model and reports the mode
  and the outstanding release inputs.
- **M3:** the report checksum was overclaimed. The wording is corrected, and a consistency check against the stored verdicts was
  added.
- **L1:** a dirty or foreign checkout reported a commit. It no longer does.
- **L3:** the internal-review banner wording no longer implies access control.
- **L5:** tests now check AST imports and literals instead of substrings; a shadow-mode spy proves zero canonical reads; the M1
  regression test was verified to fail without the fix.

Accepted, with documentation: **L2** (the version-binding scope) and **L4** (the direct-construction default).
