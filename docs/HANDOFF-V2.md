# ATLAS / WASET — ENGINEERING HANDOFF
## Editor Intelligence MVP — Updated Source of Truth

**Status:** Active product specification / engineering handoff  
**Company:** Waset Co Studio  
**Product:** Atlas  
**Scope:** Internal Waset system only  
**Current MVP scope:** Editor intelligence and editor performance visibility only  
**Last updated:** September 29, 2026  
**Document authority:** This document supersedes earlier handoff wording where there is any conflict.

---

# 0. HOW TO USE THIS DOCUMENT

This file is the current source of truth for the Atlas Editor Intelligence MVP.

Engineering, design, QA, and future agents must follow the rules below exactly.

If a requirement is explicitly marked as **locked**, it must not be reinterpreted.

If a threshold or business rule is explicitly marked as **not yet approved**, engineering must not invent one. The system may prepare a configurable implementation, but the product must not present an unsupported judgment as fact.

When the product can either:
1. show a supported fact, or
2. invent a stronger interpretation,

Atlas must choose the supported fact.

The product must remain useful without AI.

---

# 1. LOCKED PRODUCT SCOPE

Atlas V1 has one visible product purpose:

> **Show management the current performance picture of each editor, explain why, and allow every important conclusion to be inspected back to Monday.com evidence.**

The current MVP is **Editors only**.

The product is not a general company dashboard.

The current visible product must not contain operational sections for:
- Clients
- Finance
- HR
- Account Managers
- Reviewers
- Production Managers
- Operations
- Commercial
- CEO chat
- Company-wide intelligence
- Profitability
- Knowledge base
- Business memory
- Generic analytics
- Other employee roles

These may be future products or future Atlas modules, but they are not part of the current Editor Intelligence MVP.

Do not show them as primary navigation items.

Do not show them as large “Coming Soon” sections.

Do not make the current MVP look incomplete by advertising unrelated future modules.

The product should feel intentionally narrow, not unfinished.

---

# 2. PRIMARY MANAGEMENT QUESTION

Every page, metric, label, summary, and interaction must help answer:

> **What is the current performance picture of this editor, and what evidence supports that picture?**

A manager should be able to determine, quickly:

- the editor’s current overall performance state
- the editor’s strongest supported signals
- the editor’s main attention areas
- whether recent performance is improving, stable, or worsening when enough data exists
- quality signals
- speed relative to the editor team for the same Video Type
- deadline performance
- current active workload where supported
- revision activity as context only
- the evidence behind every important conclusion

The system should not require the manager to manually combine 10–20 raw metrics before understanding the editor.

---

# 3. PRIMARY USER

The current MVP is for Waset management.

The only employee role modeled as a performance subject in V1 is:

> **Editor**

Other roles may appear only when necessary to correctly attribute events or explain workflow state.

Other roles do not receive scorecards, dashboards, rankings, or profiles in this version.

---

# 4. PRIMARY DATA SOURCE

V1 uses:

> **Monday.com only**

No additional production data source is required for the MVP.

Supported Monday data includes, where available:

- stable editor / assignee identity
- status activity history
- Requested ETA
- Video Type
- Performance labels / issues
- revision status activity
- reviewer / project metadata where already present
- project identifiers and names
- relevant timestamps

Atlas must not present a metric or conclusion as fact unless the required source evidence exists.

---

# 5. ACTOR ATTRIBUTION — LOCKED BUSINESS RULE

The Monday actor display name **Waset Co** does not identify one real person.

The same account is used by multiple people and workflows.

Therefore:

> **Never infer the real actor from the display name alone. Infer responsibility from the exact status transition or action type.**

Authoritative transition rules:

| Transition | Real actor / meaning |
|---|---|
| `Ready to Edit → In Progress` | Production Manager |
| `In Progress → Ready For Approval` | Editor |
| `Ready For Approval → Approved / Sent / Delivered` | Production Manager |
| transition into `Revisions` | Status change is performed by the Editor; the revision itself represents a client revision |
| `Revisions → Ready For Approval` | Editor |
| `Ready For Approval → In Progress` | Editor |

These rules are deterministic business logic.

Do not ask AI to infer these actors.

Do not attribute all actions by the `Waset Co` account to the editor.

---

# 6. EDITOR WORK CYCLE — LOCKED

The editor execution interval is:

```text
In Progress
    ↓
Ready For Approval
```

For every valid work cycle:

```text
Editor Work Start = timestamp entering In Progress
Editor Work End   = timestamp entering Ready For Approval
Editor Work Time  = Work End - Work Start
```

Do not start the editor speed clock at assignment time.

Do not start the editor speed clock at `Ready to Edit`.

Invalid or incomplete cycles must be excluded or flagged.

---

# 7. DEADLINE LOGIC — LOCKED

`Requested ETA` is considered usable for the current MVP.

Deadline delta:

```text
deadline_delta = ready_for_approval_at - requested_eta
```

Interpretation:

```text
negative delta = early
positive delta = late
```

If the product uses an “on time” tolerance window, that tolerance must exist as an explicit configuration value.

It must not be silently hard-coded in multiple places.

It must not differ between Arabic and English.

It must not differ between summary and detail views.

---

# 8. SPEED COMPARISON — LOCKED

Projects must not be compared across different Video Types as though they require equal effort.

All editor speed comparisons must be segmented by `Video Type`.

Example:

```text
Editor Class A median = 4.8h
Team Class A median   = 6.0h
```

A supported statement is:

> The editor is 20% faster than the current team benchmark for Class A.

An unsupported statement is:

> Class A should take 6 hours.

The team benchmark is descriptive, not an official SLA.

Comparison scope:

> **The editor is compared against the whole editor team inside the same Video Type.**

Do not compare only against same-level editors in V1.

Every speed comparison must show sample size.

---

# 9. QUALITY SIGNALS — LOCKED

Editor quality uses Monday Performance labels / issues.

Known examples include:

## Negative / issue labels
- Did Not Follow Instructions
- Quality Issue
- Technical Issues
- Recurring Mistakes
- Excessive Revisions
- Late Delivery
- Poor Communication

## Positive / context labels
- Exceptional Quality
- Additional Revisions
- Client Praise
- High Workload
- On Time Delivery

The active set should come from real Monday data/configuration where possible.

For V1:

> **1 label occurrence = 1 event.**

Do not add severity weights.

Do not add hidden AI reweighting.

Do not infer personality traits from quality labels.

Positive evidence must be processed with the same technical seriousness as negative evidence.

---

# 10. REVISION RULE — LOCKED

A transition into `Revisions` means a client revision occurred.

Current Monday data does not reliably identify the cause.

Therefore Atlas V1 must not classify a revision as:

- editor-caused
- client-preference-caused
- AM-caused
- reviewer-caused
- quality-caused

Revision information may include:

- revision events
- projects with revisions
- revision rate

But:

> **Revision activity is context only and must not reduce the editor’s performance score or status by itself.**

The UI must not use visual treatment that implies revisions automatically represent editor fault.

---

# 11. DETERMINISTIC INTERPRETATION LAYER

Atlas must move from a raw-data report toward a management intelligence product, but the interpretation layer must remain deterministic and auditable.

The required interpretation layer includes:

- Overall Status
- Strengths
- Attention Areas
- Recent Change
- Trend
- Recognition signals
- Attention signals

However, engineering must not invent unapproved business thresholds.

Therefore:

1. Build these as versioned, configurable rule engines.
2. Keep all rules explicit.
3. Keep the underlying component metrics visible.
4. Store or expose the rule version used.
5. Never let an LLM create the classification from raw data.
6. If a required threshold is not yet approved, show the supported raw metric or “Not enough approved logic to classify” rather than inventing a judgment.

The product requirement is that these deterministic classifications exist before the MVP is considered complete.

---

# 12. INFORMATION ARCHITECTURE — LOCKED

The visible product structure should be:

```text
Editors
  ↓
Editor Profile
  ↓
Evidence
```

The product must not expand into a multi-department operating system in this release.

Recommended visible navigation:

- Editors
- Language switch
- Small system/data status access if needed

Do not use top-level navigation for unrelated future modules.

---

# 13. REQUIRED EDITOR PROFILE ORDER

The Editor Profile should present information in this order:

1. Overall Status
2. Short explanation: “Why this status?”
3. What changed recently
4. Strengths
5. Attention Areas
6. Quality
7. Speed / Productivity
8. Deadline Performance
9. Revision Context
10. Current Active Work / Capacity, only when supported
11. Historical Context
12. Evidence

The user should first understand the editor, then inspect the numbers, then inspect the raw evidence.

Do not force the manager to reverse-engineer the conclusion from tables.

---

# 14. THE 40 REQUIRED PRODUCT CHANGES

The following 40 items are required for the current Editor Intelligence MVP.

Each item includes:
- **Requirement**
- **Do**
- **Do not**
- **Acceptance criteria**

---

## 1. Replace the home page with an Editors Overview

### Requirement
The primary screen must be an Editors Overview, not a generic company dashboard.

### Do
Show one clear card per editor with only high-value management information:
- editor name
- avatar or stable visual identity
- current Overall Status
- strongest supported positive signal
- main attention area
- recent trend, if supported
- sample size / project count used for the current view

### Do not
Do not use the home page for:
- client modules
- company-wide analytics
- finance
- generic operations
- unrelated “coming soon” sections

### Acceptance criteria
A manager can open Atlas and understand the current state of the editor team without opening a separate company dashboard.

---

## 2. Remove non-editor product sections from primary navigation

### Requirement
The current navigation must communicate that Atlas V1 is an editor intelligence product.

### Do
Keep only editor-related navigation plus utility controls such as language and system status.

### Do not
Do not expose top-level navigation for future Client, Finance, HR, AM, Reviewer, Operations, Commercial, or CEO features.

### Acceptance criteria
The visible information architecture contains no primary section that evaluates or analyzes a non-editor role or business function.

---

## 3. Replace “Not evaluated yet” with a real deterministic Overall Status

### Requirement
Every editor with sufficient valid evidence must receive an Overall Status.

Candidate labels may include:
- Strong
- Good
- Mixed
- Needs Attention
- Under Pressure

### Do
Implement Overall Status through deterministic, versioned rules based on approved components such as:
- Quality Signals
- Speed vs Team Benchmark by Video Type
- Deadline Performance

Revision Context must remain non-scoring.

### Do not
Do not let AI decide the Overall Status.
Do not invent thresholds in application code without approval.

### Acceptance criteria
For every classified editor, the same inputs and same rule version always produce the same Overall Status.

---

## 4. Make Overall Status explainable

### Requirement
The manager must immediately understand why an editor received a status.

### Do
Directly beneath the status, show 2–3 concise evidence-backed reasons.

Example structure:

```text
Why this status:
- Faster than the Class A team benchmark.
- Deadline performance improved in the recent period.
- Late Delivery remains the most repeated negative signal.
```

### Do not
Do not show personality judgments.
Do not use unsupported causal language.

### Acceptance criteria
Every sentence in “Why this status” can be traced to a computed metric and evidence set.

---

## 5. Add “What changed recently?”

### Requirement
Every Editor Profile must explain recent movement, not only lifetime totals.

### Do
Compare a recent window with the immediately preceding equivalent window.

Recommended default:
- recent period = last 30 completed days
- comparison period = previous 30 completed days

The date range must be visible.

### Do not
Do not call a change “improvement” or “decline” unless an approved rule defines what is materially better or worse.

### Acceptance criteria
The profile shows either:
- a supported recent change,
- “stable” under an approved rule,
- or “not enough data”.

---

## 6. Add an explicit editor Trend

### Requirement
Where evidence is sufficient, show:
- Improving
- Stable
- Declining

### Do
Make trend deterministic and metric-driven.

### Do not
Do not infer trend from visual intuition.
Do not generate trend from an LLM.

### Acceptance criteria
Trend has:
- a documented comparison period
- minimum sample requirements
- explicit material-change rules
- a visible fallback when evidence is insufficient

---

## 7. Reduce metrics on the editor card

### Requirement
The Editors Overview card must remain scannable.

### Do
Limit the primary card to approximately 3–4 core indicators, for example:
- Overall Status
- Deadline
- Quality
- Speed
- optional current load indicator only when valid

### Do not
Do not place full tables, all Video Types, or the entire evidence history on the card.

### Acceptance criteria
The manager can compare the team visually without reading a report inside each card.

---

## 8. Rebuild the Editor Profile as a layered experience

### Requirement
Summary first, detail second, evidence third.

### Do
Use the profile order defined in Section 13.

### Do not
Do not begin the profile with large raw tables.

### Acceptance criteria
The first viewport contains enough information to understand the editor before scrolling into detailed analytics.

---

## 9. Add a real Strengths section

### Requirement
Atlas must identify supported positive performance signals.

### Do
Examples of valid strengths:
- faster than team benchmark in a specific Video Type
- strong deadline performance
- positive label frequency
- Client Praise occurrences
- Exceptional Quality occurrences
- low issue rate across a meaningful sample

### Do not
Do not convert absence of negative labels into exaggerated praise.
Do not make character judgments.

### Acceptance criteria
Each strength has measurable evidence and can link to detail.

---

## 10. Add a real Attention Areas section

### Requirement
Atlas must summarize repeated or material negative signals.

### Do
Examples:
- repeated Late Delivery labels
- repeated Poor Communication labels
- declining deadline performance
- slower-than-team performance in a specific Video Type when sample size is valid

### Do not
Do not describe the person as lazy, careless, difficult, unreliable, or similar personality labels.

### Acceptance criteria
Each attention area is supported by concrete evidence and has a drill-down path.

---

## 11. Make Quality interpretable, not just count-based

### Requirement
Quality must explain rate and distribution, not only totals.

### Do
Show:
- positive label count
- negative label count
- label breakdown
- issue rate per project
- positive signal rate per project
- most repeated labels
- recent trend when valid

### Do not
Do not present a raw count without relevant denominator/context when that count may be misleading.

### Acceptance criteria
A manager can distinguish “12 issues across 150 projects” from “12 issues across 15 projects”.

---

## 12. Complete Positive Signal handling

### Requirement
Positive evidence must be processed and displayed as first-class evidence.

### Do
Map and surface supported positive labels such as:
- Exceptional Quality
- Client Praise
- On Time Delivery
- other approved positive/context labels

### Do not
Do not build a product that is technically better at surfacing negative evidence than positive evidence.

### Acceptance criteria
The positive-label pipeline is tested with the same rigor as negative-label processing.

---

## 13. Keep Speed comparison inside the same Video Type

### Requirement
All speed evaluation remains segmented by Video Type.

### Do
Compare:
```text
Editor benchmark for Video Type X
vs
Team benchmark for Video Type X
```

### Do not
Do not create a single raw “average editor speed” across unrelated Video Types and use it as a performance judgment.

### Acceptance criteria
Every speed judgment references a specific Video Type or a clearly defined aggregation of valid per-type comparisons.

---

## 14. Add a Speed summary before the detailed table

### Requirement
The manager should understand the speed picture before reading all Video Types.

### Do
Summarize, for example:

```text
Faster than team benchmark in 3 Video Types
Similar in 2
Slower in 1
```

Only use categories with approved comparison thresholds.

### Do not
Do not force the user to manually interpret a long table.

### Acceptance criteria
The detailed per-Video-Type evidence remains available below or via drill-down.

---

## 15. Always show Sample Size

### Requirement
Every comparison must expose the evidence volume behind it.

### Do
For example:

```text
Editor sample: 12 projects
Team sample: 83 projects
```

### Do not
Do not give a strong-looking comparison with hidden sample size.

### Acceptance criteria
No speed benchmark is displayed without sample size.

---

## 16. Turn Deadline Performance into a clear management summary

### Requirement
Deadline information must answer whether the editor reaches Ready For Approval before or after Requested ETA.

### Do
Show:
- Early %
- On-time %
- Late %
- average or median early/late margin
- recent trend when supported

Also show a concise summary sentence.

### Do not
Do not make the user interpret only three raw counts.

### Acceptance criteria
The manager can understand current deadline performance in one glance and inspect the underlying projects.

---

## 17. Make the On-Time tolerance explicit and centralized

### Requirement
If an on-time tolerance is used, it must be one configured business value.

### Do
Store it centrally in configuration and surface it in metric documentation.

### Do not
Do not hard-code different tolerances in different components.

### Acceptance criteria
Arabic, English, summary views, detail views, tests, and exports all use the same tolerance.

---

## 18. Keep Revisions as context only

### Requirement
Revisions must remain visible but non-judgmental.

### Do
Show:
- projects with revisions
- revision events
- revision rate

Add clear explanatory copy:

> Revision activity is informational and does not currently indicate editor fault.

### Do not
Do not display revisions as an automatic red warning.
Do not describe high revisions as poor editor quality.

### Acceptance criteria
Revision data appears in a separate context section and is not used as negative evidence by itself.

---

## 19. Remove Revisions from scoring and Overall Status

### Requirement
Revision count/rate must not reduce editor scoring or status in V1.

### Do
Keep revision calculations isolated from scored performance components.

### Do not
Do not indirectly reintroduce revision penalties through hidden weights or AI summaries.

### Acceptance criteria
Changing revision count alone cannot worsen Overall Status when all scored metrics remain unchanged.

---

## 20. Fix Current Work / Capacity semantics

### Requirement
“Current Work” must represent actual active work, not historical/completed states.

### Do
Define the exact active statuses allowed in the current workload count.

Examples may include:
- In Progress
- Ready For Approval
- Revisions
- other explicitly approved active states

### Do not
Do not count `Done`, `Sent`, or other completed/historical states as current workload.

### Acceptance criteria
Current Work count equals the set of projects currently in approved active statuses only.

---

## 21. Do not infer pressure when Capacity logic is not approved

### Requirement
Atlas must not call an editor “Under Pressure” from unsupported workload assumptions.

### Do
If a validated capacity rule does not yet exist, show factual counts such as:

```text
Active projects: 6
In Progress: 2
Ready For Approval: 3
Revisions: 1
```

### Do not
Do not label workload as normal/high/overloaded without approved thresholds.

### Acceptance criteria
Every pressure/capacity classification has an explicit rule; otherwise only facts are shown.

---

## 22. Add “Needs Attention Now” signals

### Requirement
Atlas should surface current issues requiring management review.

### Do
Use deterministic triggers such as:
- repeated recent issue labels
- a material negative deadline trend
- a valid deterioration in a performance component

### Do not
Do not turn the signal into a disciplinary recommendation.

### Acceptance criteria
Every attention signal states the supporting metric, period, and evidence.

---

## 23. Add Recognition signals

### Requirement
Atlas must also surface strong recent performance.

### Do
Possible evidence:
- sustained strong deadline performance
- repeated positive labels
- valid strong speed performance
- meaningful positive improvement

### Do not
Do not create recognition from weak samples.

### Acceptance criteria
Recognition uses explicit evidence and minimum sample rules.

---

## 24. Add a visible, consistent time window

### Requirement
Every performance summary must make its date range clear.

### Do
Use a default recent window for the primary view and allow controlled period changes.

Recommended default:
- last 30 completed days for “current/recent”
- historical context separately

### Do not
Do not silently mix all-time and recent metrics in the same summary.

### Acceptance criteria
The active time window is visible and consistent across all metrics in the same view.

---

## 25. Keep historical context secondary

### Requirement
History should explain direction, not dominate the current-state page.

### Do
Use a compact historical chart or section, for example the last 6 months.

### Do not
Do not place a large month-by-month data table above the current performance summary.

### Acceptance criteria
The manager sees current state first and history second.

---

## 26. Add Data Coverage / Confidence context

### Requirement
The product must show when metrics are based on limited or incomplete evidence.

### Do
Examples:

```text
Deadline coverage: 32 / 41 projects
Speed coverage: 28 / 41 projects
Quality labels: 41 / 41 projects
```

Where useful, expose a neutral data-coverage indicator.

### Do not
Do not represent data completeness as employee performance.

### Acceptance criteria
Missing-data volume is visible for important metrics.

---

## 27. Exclude or flag bad records instead of silently corrupting metrics

### Requirement
Data quality checks are mandatory.

### Do
Detect at minimum:
- missing editor identity
- missing Video Type
- missing Requested ETA where deadline metrics require it
- missing In Progress timestamp
- missing Ready For Approval timestamp
- impossible timestamp ordering
- duplicate activity events
- contradictory status transitions
- unresolved actor interpretation

### Do not
Do not silently include invalid records in performance metrics.

### Acceptance criteria
Every metric can report:
- valid records included
- records excluded
- exclusion reasons

---

## 28. Improve the Evidence Drawer

### Requirement
Every important management conclusion must be inspectable.

### Do
Clicking an insight should reveal supporting:
- project(s)
- metric values
- date/time
- relevant label or transition
- evidence count
- period used

### Do not
Do not make the manager leave Atlas to understand why a statement exists unless a direct Monday link is intentionally provided as the final evidence source.

### Acceptance criteria
A manager can trace a high-level conclusion to specific evidence in a few interactions.

---

## 29. Move raw Evidence out of the primary visual hierarchy

### Requirement
Evidence remains essential but should be secondary to comprehension.

### Do
Use:
- drawers
- expandable sections
- detail panels
- dedicated evidence view

### Do not
Do not lead the page with raw event logs.

### Acceptance criteria
The primary page communicates the editor state before the evidence detail is opened.

---

## 30. Keep AI as an optional summarization layer only

### Requirement
AI may rewrite deterministic facts into concise management language.

### Do
Allow AI to summarize already-computed facts.

Example:

> Faster than the team benchmark in Class A, while recent negative signals are concentrated in Late Delivery.

### Do not
AI must not:
- invent metrics
- classify actor identity
- classify revision causes
- create scoring rules
- generate Overall Status directly from raw data
- make psychological judgments

### Acceptance criteria
Disabling AI does not remove any metric, status rule, evidence, or essential decision support.

---

## 31. Suppress AI certainty when evidence is weak

### Requirement
The wording must reflect evidence limitations.

### Do
Use explicit fallbacks such as:

```text
Not enough recent data to identify a reliable trend.
```

### Do not
Do not generate confident prose from insufficient sample size.

### Acceptance criteria
AI or templated summaries receive structured data-quality flags and respect them.

---

## 32. Fix snapshot consistency across root, Arabic, and English routes

### Requirement
All user-facing routes must display the same published dataset version.

### Do
The root route, Arabic route, and English route must resolve to the same current snapshot/release.

### Do not
Do not allow language pages to be generated from different publication states.

### Acceptance criteria
For the same publication:
- editor count matches
- snapshot timestamp matches
- metric values match
- only localized strings differ

This is a release-blocking issue.

---

## 33. Use one shared View Model for Arabic and English

### Requirement
Localization must not duplicate business logic.

### Do
Compute all metrics and classifications once.
Render localized text from the same structured data.

### Do not
Do not implement separate Arabic metric logic or English metric logic.

### Acceptance criteria
Given the same snapshot and language-independent inputs, Arabic and English produce identical numeric and classification results.

---

## 34. Improve responsive behavior for large screens

### Requirement
Atlas must use available screen space intelligently.

### Do
On large displays:
- allow more editor cards per row
- widen analytic sections where useful
- use two- or three-column layouts where readability improves
- preserve comfortable maximum text line lengths

### Do not
Do not leave a narrow desktop layout floating in the middle of a very wide monitor.
Do not stretch paragraphs into unreadably long lines.

### Acceptance criteria
The dashboard meaningfully adapts from laptop to large desktop displays.

---

## 35. Reduce unnecessary vertical scrolling

### Requirement
The most important editor information must appear near the top.

### Do
The first viewport should prioritize:
- Overall Status
- Why this status
- Strength
- Attention area
- core metrics
- trend

### Do not
Do not require multiple screens of scrolling before the manager understands the editor.

### Acceptance criteria
A manager can understand the top-level state without opening lower-detail sections.

---

## 36. Add useful filtering without building an employee leaderboard

### Requirement
Managers need to find relevant editors quickly without ranking people from best to worst.

### Do
Allow filters such as:
- status
- needs attention
- recognition
- recent change
- name

### Do not
Do not create:
- “Top Editors”
- “Worst Editors”
- rank 1, 2, 3…
- competitive employee leaderboard

### Acceptance criteria
The system supports targeted review without presenting a best-to-worst ranking.

---

## 37. Add editor search

### Requirement
The user must be able to find an editor directly.

### Do
Provide fast search by editor name and stable mapped identity/alias where needed.

### Do not
Do not require scrolling through all cards as the team grows.

### Acceptance criteria
Typing an editor’s known name returns the correct profile/card.

---

## 38. Hide unrelated future features from the current product surface

### Requirement
Future scope must not weaken the clarity of the current MVP.

### Do
Keep future modules in product planning, not in the main operational UI.

### Do not
Do not show large placeholder sections for:
- clients
- finance
- HR
- company intelligence
- other roles

### Acceptance criteria
A new user can correctly describe Atlas V1 as “editor intelligence” after seeing the product.

---

## 39. Do not add Client Intelligence in the current MVP

### Requirement
Client Intelligence remains explicitly out of scope for this release.

### Do
Keep architecture extensible where reasonable.

### Do not
Do not implement client prediction, client scoring, client profiles, profitability, or chat intelligence as part of the Editor MVP.

### Acceptance criteria
No client analytics module is required for MVP launch.

---

## 40. Adopt a strict Definition of Done for the Editor MVP

### Requirement
The MVP is complete only when the manager can open any editor profile and quickly answer:

1. What is this editor’s current status?
2. Why is that the current status?
3. What are the strongest positive signals?
4. What needs attention?
5. Is recent performance improving, stable, or declining, when evidence is sufficient?
6. How does speed compare with the team for the same Video Types?
7. How is deadline performance?
8. What quality signals appear most often?
9. What revision activity exists, without blaming the editor?
10. What is the current active workload, if valid?
11. How complete is the underlying data?
12. Can every important conclusion be traced back to Monday evidence?

### Acceptance criteria
If the manager still needs to manually combine many tables to answer these questions, the MVP is not finished.

---

# 15. CURRENT WORK / CAPACITY RULE

The current workload section is descriptive unless explicit capacity thresholds are later approved.

At minimum, the UI may show counts of projects in approved active statuses.

Completed/historical states must not inflate current workload.

`Done`, `Sent`, `Delivered`, and equivalent completed states should not be counted as active work unless a future business rule explicitly says otherwise.

A label such as `Under Pressure` must not be shown until a deterministic capacity rule exists.

---

# 16. OVERALL STATUS IMPLEMENTATION CONTRACT

Overall Status is required for the finished MVP, but it must not be improvised.

Engineering must implement the following contract:

```text
input:
  quality_component
  speed_component
  deadline_component
  data_coverage
  approved_rule_version

output:
  overall_status
  reasons[]
  rule_version
  evidence_refs[]
```

Revision activity must not be a scored input.

Current workload must not be a scored input unless a later approved business rule explicitly adds it.

The final status thresholds must be:
- deterministic
- documented
- configurable/versioned
- approved before production classification is considered final

If thresholds are still under calibration, the product may expose component results, but must not pretend an unapproved status is authoritative.

---

# 17. TREND IMPLEMENTATION CONTRACT

The default recent trend comparison should use:

```text
Recent window:
last 30 completed days

Comparison window:
the immediately preceding 30 completed days
```

The UI must display the actual dates.

Trend can only be labeled `Improving`, `Stable`, or `Declining` when:
- minimum sample requirements are met
- metric-specific material-change thresholds are defined
- the same rule is used consistently

Otherwise show:

```text
Not enough data
```

or the factual raw delta without judgment.

---

# 18. EVIDENCE CONTRACT

Every major conclusion must expose enough structured evidence to answer:

```text
What claim was made?
Which metric produced it?
Which projects/events contributed?
What date range was used?
What sample size was used?
Which rule version produced the classification?
Were any records excluded?
Why were they excluded?
```

Unsupported prose must never be stored or presented as truth.

---

# 19. DATA QUALITY CONTRACT

For every major metric, Atlas should be capable of reporting:

```text
eligible_records
included_records
excluded_records
exclusion_reasons
coverage_ratio
```

Bad records must not disappear silently.

The manager does not need to see all technical details by default, but the product must preserve them for auditability.

---

# 20. LOCALIZATION CONTRACT

Arabic and English are two renderings of the same product state.

They must share:

- the same snapshot
- the same metrics
- the same status classifications
- the same trend classifications
- the same evidence
- the same date ranges
- the same rule versions

Only presentation strings and locale formatting may differ.

---

# 21. RELEASE CONSISTENCY CONTRACT

Publishing must be atomic from the user’s point of view.

The following must not happen:

```text
/              → old snapshot
/en/...        → new snapshot
/ar/...        → different snapshot
```

All public routes in one release must resolve to the same published dataset version.

The snapshot/release identifier should be visible or inspectable.

A release with route-level snapshot disagreement must fail QA.

---

# 22. UX PRINCIPLE: INTERPRETATION BEFORE RAW DETAIL

The target user experience is:

```text
Fact
  ↓
Deterministic interpretation
  ↓
Management summary
  ↓
Detail
  ↓
Evidence
```

Not:

```text
Large raw table
  ↓
More raw tables
  ↓
Manager manually interprets everything
```

Atlas must reduce management interpretation effort without hiding the evidence.

---

# 23. UX PRINCIPLE: FAIRNESS

The system must avoid making one kind of evidence visually dominant without justification.

Specifically:

- positive signals and negative signals must both be discoverable
- revisions must not visually imply fault
- small samples must not look as authoritative as large samples
- missing data must not become negative performance
- workload must not become performance unless approved
- historical poor performance must not permanently hide recent improvement
- recent good performance must not erase relevant longer-term context

---

# 24. UX PRINCIPLE: NO LEADERBOARD

Atlas is an editor understanding tool, not an employee competition system.

Do not implement:
- best editor
- worst editor
- numbered rank
- podium
- competitive scoring table

Managers may filter by condition, but the product must not reduce people to a best-to-worst ordering.

---

# 25. AI ROLE — FINAL MVP RULE

AI is optional.

AI may:
- summarize deterministic metrics
- simplify language
- produce concise management wording from structured facts

AI may not:
- calculate core metrics
- invent missing facts
- determine actor identity
- determine revision cause
- define scoring rules
- determine Overall Status directly from raw events
- determine trend directly from unstructured intuition
- make personality judgments
- recommend termination, promotion, salary changes, or disciplinary action

The editor dashboard must remain fully functional with AI disabled.

---

# 26. REQUIRED MVP PAGE MODEL

## A. Editors Overview

Each editor card should provide:
- identity
- Overall Status
- one major strength
- one major attention area
- recent trend when valid
- 3–4 core metrics
- sample size / coverage context

## B. Editor Profile

Top section:
- Overall Status
- Why this status
- What changed recently
- Strengths
- Attention Areas

Middle section:
- Quality
- Speed
- Deadline
- Revision Context
- Current Work, where supported

Lower section:
- historical context
- data coverage
- evidence

## C. Evidence

Evidence should open from claims and metrics rather than forcing the user to start with raw logs.

---

# 27. OUT OF SCOPE — FINAL LIST FOR CURRENT RELEASE

Do not build these for the current Editor MVP:

- external customer product
- SaaS multi-tenancy
- tenant onboarding
- subscriptions
- client intelligence
- client prediction
- client profitability
- finance intelligence
- HR analytics
- Account Manager KPIs
- Reviewer KPIs
- Production Manager KPIs
- Operations KPIs
- Commercial KPIs
- General Manager KPIs
- CEO chat
- open-ended company Q&A
- knowledge base
- business memory
- semantic search
- autonomous agents
- autonomous business actions
- ML deadline prediction
- promotion scoring
- salary recommendations
- termination recommendations
- revision-cause AI classification
- employee leaderboard

---

# 28. RECOMMENDED IMPLEMENTATION ORDER

## P0 — Trust and consistency

Complete first:
1. snapshot consistency across all routes
2. shared Arabic/English View Model
3. active-work semantics
4. data quality exclusions and coverage
5. evidence traceability
6. positive-label mapping validation

Do not polish management conclusions on top of inconsistent data.

## P1 — Deterministic intelligence

Then implement:
1. Overall Status rule framework
2. Strengths
3. Attention Areas
4. Recent Change
5. Trend
6. Recognition
7. Needs Attention Now
8. management summaries

## P2 — UX hierarchy

Then rebuild:
1. Editors Overview
2. Editor Profile hierarchy
3. reduced card metrics
4. compact speed summary
5. compact deadline summary
6. secondary history
7. evidence drawers
8. large-screen responsiveness
9. search and filters

## P3 — Optional AI wording

Only after P0–P2 are trusted.

---

# 29. QA REQUIREMENTS

The release must include deterministic tests for:

- actor attribution rules
- work-cycle reconstruction
- deadline delta
- on-time tolerance
- Video Type segmentation
- team benchmark calculation
- sample sizes
- positive label counts
- negative label counts
- revision non-scoring behavior
- current active-work filtering
- data-quality exclusions
- status rule determinism
- trend rule determinism
- Arabic/English result parity
- snapshot/release parity across routes

For revision behavior, include a regression test proving:

```text
If only revision count changes,
Overall Status does not worsen.
```

For localization, include a regression test proving:

```text
Same snapshot + same editor
=> same numeric results and classifications in Arabic and English.
```

---

# 30. FINAL MVP SUCCESS CRITERIA

Atlas Editor Intelligence MVP is successful when management can open the product and, with minimal reading, understand:

> **Who is doing well, who needs attention, what changed recently, and exactly what evidence supports that view — without Atlas inventing facts or unfairly blaming editors.**

The current MVP is not successful merely because it has:
- many dashboards
- many charts
- AI prose
- large historical tables
- many future modules

The product succeeds when it produces a fair, fast, evidence-backed editor picture.

---

# 31. FINAL PRODUCT SUMMARY

The current Atlas product should be understood as:

```text
Monday.com
   ↓
Activity / Status History
   ↓
Actor Interpretation Rules
   ↓
Editor Work Cycles
   ↓
Video-Type Segmentation
   ↓
Requested ETA Comparison
   ↓
Performance Labels
   ↓
Data Quality Validation
   ↓
Deterministic Editor Metrics
   ↓
Deterministic Interpretation Layer
   ↓
Editors Overview
   ↓
Editor Profile
   ↓
Evidence
   ↓
Optional AI Summary
```

The guiding product question is:

> **What is the current state of this editor, why, and what evidence proves it?**

Anything that does not directly support that question should remain outside the current MVP.
