# Atlas V1 deterministic rules

These rules are the authoritative baseline until the missing original execution-plan file is restored.

1. **Monday is authoritative.** Persist Monday board/item/column/event identifiers and source timestamps. Derived data must point back to those identifiers.
2. **Editor is the evaluated entity.** Metrics are attributed to the editor responsible for the work interval, not to the reviewer, manager, client, or AI.
3. **Work duration is exact.** Measure from the transition into `In Progress` through the transition into `Ready For Approval`. Waiting, revision, and review intervals are not silently substituted.
4. **Deadline is not Requested ETA.** Store, display, and calculate them independently. Never coalesce one into the other.
5. **Comparable benchmarks only.** An editor/project is benchmarked only against records with the same canonical `video_type`.
6. **Waset Co actor attribution is deterministic.** Resolve actors using canonical Monday person/team IDs and a versioned mapping. Ambiguity goes to an exception queue; no fuzzy AI choice.
7. **Revisions are context.** Revision counts and notes can explain outcomes but cannot directly lower a quality score without an explicit deterministic business rule.
8. **Quality is label-derived.** Quality values come from approved Monday labels and a versioned label mapping.
9. **Evidence is mandatory.** Every metric stores source record IDs, event IDs, field values, formula/rule version, and calculation time.
10. **AI is not authoritative.** AI can summarize, investigate, recommend, or flag anomalies. It cannot invent facts or overwrite deterministic source-derived values.

## Contract ownership

Changes under `contracts/` require a designated contract owner review plus compatibility tests. Builders may propose contract changes; the arbiter cannot waive contract review.

