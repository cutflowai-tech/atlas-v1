# Intelligence V2: Monday data capability map

Task 2 of the Intelligence V2 brief. The machine-readable map is
[`config/intelligence-v2-data-capabilities.json`](../config/intelligence-v2-data-capabilities.json). Each detector declares the
signals it requires (`investigation/catalog.py`), and `tests/test_investigation_governance.py` fails if a detector requires a
signal classed `unavailable` or `unsafe_to_infer`. A detector may depend on such a signal only after this map is updated with
evidence.

The map was verified against the pipeline code and production run `20260929T130736Z-e6d03314e704`:

- 1,305 items;
- 17,908 accepted status events;
- 861 completed first cycles, 681 of them attributed to an Editor;
- contract 1.5.0.

## Summary

| Signal | Class | Key limitation |
|---|---|---|
| Project / item ID, board ID, status event ID | reliable | one board only |
| Status history | reliable | 804 unknown and 231 cleared status logs are quarantined; spans containing one are not assigned to a stage |
| Editor execution interval (first In Progress → first Ready For Approval) | reliable | elapsed clock time, not effort |
| Editor identity (at Ready For Approval) | reliable | 180 of 861 completed cycles are unattributed; open cycles are not attributed |
| Current Editor of open work | usable with limitations | current snapshot only |
| Editor assignment time | usable with limitations | time the value was set, not when work was seen |
| Item creation time | usable with limitations | missing for items created before the window |
| Video Type (at Ready For Approval) | reliable | the only complexity control |
| Requested ETA (D19) | reliable | 32 date-only and 3 missing among 681; in 58 cycles it was first observed after In Progress |
| ETA in effect at work start | usable with limitations | context only, never a metric input |
| Execution runway (ETA − In Progress) | usable with limitations | flagged when the ETA was observed after work start |
| Deadline result | reliable | none |
| Performance labels | usable with limitations | hand-applied, so rates are lower bounds; attributed via the first completed cycle |
| Label timestamp | reliable | never moves the project's window (D42) |
| Client / internal revision | reliable | context only (D31) |
| Stage durations | usable with limitations | the last visit is censored; unknown-status spans are excluded |
| Post-editor delivery (Sent / Done after RFA) | usable with limitations | who moved the card is mostly unidentifiable |
| Transition role | usable with limitations | 13,320 of 17,908 transitions have no role rule |
| Concurrent workload history | usable with limitations | lower bound (attributed completed first cycles only); no capacity rule |
| Current open work (D33) | reliable | current state only |
| **Revision cause** | **unavailable** | no reason field |
| **Reviewer identity** | **unavailable** | not ingested; out of scope |
| **Client identity** | **unavailable** | out of scope |
| **Complexity beyond Video Type** | **unavailable** | not captured |
| **Working hours / effort** | **unavailable** | not captured |
| **Priority / queue position** | **unavailable** | not captured |
| **Person behind the shared Waset Co account** | **unsafe to infer** | forbidden by rule |
| **Person or role behind individual accounts** | **unsafe to infer** | `user_id` is audit metadata only |
| **Item name text** | **unsafe to infer** | may name clients; not used |
| **Meaning of retired statuses** | **unsafe to infer** | D18 |

## Important missing information

1. **Why a project was late, or revised.** Only timestamps exist. Every V2 statement about cause is therefore a *hypothesis* or a
   *suggested investigation*, never a finding.
2. **Effort.** Elapsed time mixes work, waiting and parallel projects. V2 reports concurrency as an association with elapsed time,
   never as a claim about how hard someone worked.
3. **Who scheduled the work.** ETA setting and card moves mostly come from the shared account. Pre-editor findings therefore name
   a **stage** (for example "entered In Progress with less runway than typical"), never a person or role.
4. **Label completeness.** Management applies labels by hand, and computed-late projects far outnumber `Late Delivery`
   labels. Label-based rates are lower bounds, and disagreement between labels and computed facts is reported as a data
   observation.
5. **Work before 2026-02-01, and work with unresolved identity.** These are excluded and counted in coverage, never imputed.
