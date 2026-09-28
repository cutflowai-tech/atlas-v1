# REAL-002: real-data validation under contract 1.3.0

- Data: the same read-only Monday extract as REAL-001 (board `5091110326`, retrieved 2026-09-28T17:45Z, SHA-256 `d38c848d…a1df9c2`, kept outside git).
- Contract: `config/monday-contract-v1.3.json` (contract 1.3.0). It adds the approved Video Type classification, the approved median statistic and Editor mapping `monday-editor-v1.1`.
- Reproduce: `PYTHONPATH=src python3 scripts/real_data_analysis.py <extract> 1.3.0` (key `validation`).

## Editor identity evidence

Monday records the Editor Name label *name* in every log. The names show that label IDs were reused for different people:

| Label ID | Names over time |
|---:|---|
| 5 | `Ahmed` (2026-03-14 → 05-04), then `Anas` (05-18 →) |
| 7 | `Mans` (03-14 → 05-06), then `Martin` (05-12 →) |
| 9 | `Michael` (03-14 → 05-03), then `Ibrahim` (05-03 →) |
| 11 | `New` (05-19), then `Refaat` (06-29 →) |
| 6 | `Will` only (292 observations, 03-14 → 09-27) |
| 12–18 | one name each since they were created (08-30 / 09-08) |

Other evidence checked:
- Monday users have no job titles or teams.
- Dropdown labels carry no user link.
- The Waset Co shared account performs most transitions.

No authoritative source ties Mario, Ibrahim, Samra, Amir, Anas, Martin or Refaat to the Editor role or to a person, so they stay quarantined.

`monday-editor-v1.1` therefore:
- corrects label 6's display name to `Will`;
- resolves an observation only when the recorded label name matches the entry.

On the current data no observation for labels 6 and 12–18 fails this guard; it protects against future label reuse.

## Coverage

| | Count |
|---|---:|
| Completed first cycles | 861 |
| With a verified Editor | 170 |
| Eligible for speed (no exclusion) | 147 |

Exclusions among completed cycles (a cycle can have several):

| Reason | Cycles |
|---|---:|
| `UNMAPPED_EDITOR` (Editor label not verified) | 518 |
| `MISSING_EDITOR_EVENT` (no Editor Name history at Ready For Approval; not backfilled) | 162 |
| `UNMAPPED_STATUS_WITHIN_CYCLE_WINDOW` (retired status meaning not established) | 120 |
| `EDITOR_CHANGED_WITHIN_CYCLE` | 11 |
| `MISSING_EDITOR` (empty Editor Name) | 10 |
| `MISSING_VIDEO_TYPE_EVENT` | 1 |

## Speed cohorts (eligible cycles)

| Cohort | Labels | Benchmark-eligible | Cycles | Editors (cycles) | ≥ 5 Editor projects |
|---|---|:---:|---:|---|---|
| 4 | Class A | yes | 44 | Will 37, Ezz 3, Sobhy 2, Ali 1, Mohamed Mansour (Office) 1 | Will |
| 5 | Class B | yes | 38 | Will 38 | Will |
| 6 | Simple Short | yes | 25 | Will 25 | Will |
| 27 | Premium Short | yes | 9 | Will 9 | Will |
| 16:4 | Ai + Class A | yes | 7 | Will 5, Sobhy 1, Ali 1 | Will |
| 10:4 | 2* + Class A | yes | 5 | Will 4, Sobhy 1 | — |
| 10:16:4 | 2* + Ai + Class A | yes | 5 | Will 4, Mohamed Mansour (Office) 1 | — |
| 8 | Class A+ | yes | 4 | Will 4 | — |
| 16:5 | Ai + Class B | yes | 3 | Will 3 | — |
| 10:5, 16:8 | 2* + Class B; Ai + Class A+ | yes | 1 each | Will | — |
| 16:26:4, 26:4, 16:22:4, 22:4, 22 | contain Unbranded or Reels Boost Pack | **no** (unclassified labels) | 1 each | — | — |

Eleven cohorts are benchmark-eligible. Five (cohort, Editor) pairs meet the minimum of 5 projects, all for Will.

**Limitation:** the verified team is effectively Will plus four Editors who started in September. The median team benchmark in each cohort is therefore dominated by Will's own projects. It becomes a meaningful team comparison only once more Editors are verified.

## Deadline coverage (Editor verified, latest Requested ETA)

| | Count |
|---|---:|
| Classified | 142 |
| Early | 98 (69.0%) |
| On time (delta exactly 0) | 0 |
| Late | 44 (31.0%) |
| Median margin | −36.9 h (early) |
| Not classifiable: date-only ETA | 9 |
| Not classifiable: missing ETA | 1 |
| Not evaluated for other reasons (e.g. unknown status in window) | 18 |

## Quality coverage (Performance Issues, 1 occurrence = 1 point)

- 26 occurrences, all for Will.
- 174 occurrences are quarantined because the project's Editor is not verified, and 59 because the project has no completed cycle.
- No positive quality source is approved: For Bonus is context only.

## Revision context (context only, never a penalty)

| Editor | Completed projects | With client revisions | Client revision events | Rate |
|---|---:|---:|---:|---:|
| Will | 157 | 135 | 314 | 86.0% |
| Sobhy | 5 | 4 | 11 | 80% |
| Ezz | 4 | 2 | 4 | 50% |
| Ali | 2 | 2 | 2 | 100% |
| Mohamed Mansour (Office) | 2 | 2 | 3 | 100% |
