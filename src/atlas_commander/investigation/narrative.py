"""Deterministic management language for Intelligence V2 findings (Tasks 47, 49, 51, 57-59), in English and Arabic.

Every sentence is rendered from a statement's ``code`` and ``params``. No sentence exists without a structured field behind it,
and no field is invented here. Wording follows fixed uncertainty standards (Task 49):

- **fact / metric**: stated plainly, always with counts and sample sizes;
- **pattern**: "X of Y", with the comparison named;
- **association**: "is associated with ... in this sample"; never "causes", "because of" or "leads to";
- **interpretation**: "This suggests / points to ...", said to be an interpretation;
- **hypothesis**: "This may warrant checking ..."; always a question for management, never a conclusion;
- **insufficient evidence**: "There is not enough comparable history to classify this pattern."

No template names a psychological trait, assigns blame, or recommends any HR action (HANDOFF §30-31, the brief's analytical
rules).

**Two languages, one structure.** English is rendered here and Arabic in ``narrative_ar`` from the *same* codes and params, with
the same keys in every table (tests enforce identical key sets and identical values). Inside rendered text, Monday values (Editor
names, Video Types, statuses, labels) are wrapped in Unicode first-strong isolates (U+2068 ... U+2069) and numbers, IDs and times
in left-to-right isolates (U+2066 ... U+2069). The document's stored ``text`` strips them (:func:`plain`); the site renders them as
``<bdi>`` so a name or a number keeps its own direction on an Arabic page. Both languages must contain exactly the same isolated
values, which is how EN/AR parity is tested.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from atlas_commander.investigation.models import ASSOCIATION, FACT, HYPOTHESIS, INTERPRETATION, METRIC, PATTERN, Finding

Params = Mapping[str, Any]

FSI, LRI, PDI = "\u2068", "\u2066", "\u2069"
CODE = "en"


def mon(value: Any) -> str:
    """A Monday value (Editor name, Video Type, status, label): shown exactly as recorded, direction-isolated."""
    return f"{FSI}{value}{PDI}"


def num(value: Any) -> str:
    """A number, ID or timestamp: left-to-right isolated, identical in both languages."""
    return f"{LRI}{value}{PDI}"


def plain(text: str) -> str:
    """Text without isolate marks (the document's stored ``text``, the review page and the CLI)."""
    return text.replace(FSI, "").replace(LRI, "").replace(PDI, "")


def pct(value: Any, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    return num(f"{float(value) * 100:.{digits}f}%")


def abs_pct(value: Any) -> str:
    """A value already in percent, without its sign (the words say the direction)."""
    return num(f"{abs(float(value)):.1f}%")


def signed_pct(value: Any) -> str:
    return num(f"{float(value):+.1f}%")


def pp(value: Any) -> str:
    return "n/a" if value is None else f"{num(f'{abs(float(value)) * 100:.0f}')} percentage points"


def hrs(value: Any) -> str:
    return "n/a" if value is None else f"{num(f'{float(value):.1f}')} h"


def plural(count: int, noun: str) -> str:
    return f"{num(count)} {noun}{'' if count == 1 else 's'}"


def _material(p: Params) -> str:
    if p.get("material_pct") is not None:
        return num(f"{p['material_pct']:.0f}%")
    return pp(p.get("material_difference"))


def who(params: Params) -> str:
    name = params.get("editor_name") or params.get("editor_id")
    return mon(name) if name else "the Editor"


def types(params: Params) -> str:
    label = params.get("cohort_label") or params.get("group_label") or params.get("cohort_key")
    return mon(label) if label else "this Video Type"


def _checks(params: Params, *wanted: str) -> Mapping[str, Any]:
    return next((row for row in params.get("checks", []) if row.get("check") in wanted), {})


OUTCOME_NAMES = {"late_delivery": "late deliveries", "negative_quality_label": "scored Negative labels", "not_late_delivery": "not-late deliveries",
                 "positive_quality_label": "scored Positive labels"}
MEASURE_NAMES = {"late_rate": "late rate", "negative_label_rate": "scored Negative label rate", "median_execution": "median execution time"}
AGAINST = {"comparison": "the previous 30 completed days", "history": "their own earlier history"}
AGAINST_TEAM = {"comparison": "the previous 30 completed days", "history": "the team's earlier history"}
SIGNALS = {"past_eta": "already past their Requested ETA", "short_remaining_runway": "have less time left than typical execution for their Video Type still needs",
           "elapsed_beyond_typical": "have been in execution longer than most comparable historical projects",
           "editor_workload_above_own_high_percentile": "belong to Editors currently holding more other active projects than the 75th percentile of their own historical workload",
           "review_wait_beyond_typical": "have waited for approval longer than most historical reviews"}
PHASES = {"pre_editor": "before the Editor", "editor_execution": "Editor execution", "review_wait": "review wait", "submission_to_delivery": "submission to delivery"}
DIMENSIONS = {"runway": "runway", "workload": "workload", "start_weekday": "start weekday", "period_of_month": "period of the month"}
VALUES = {"short": "short", "adequate": "adequate", "higher": "higher", "lower": "lower", "days_01_10": "days 1-10", "days_11_20": "days 11-20",
          "days_21_end": "day 21 to month end", "Monday": "Monday", "Tuesday": "Tuesday", "Wednesday": "Wednesday", "Thursday": "Thursday",
          "Friday": "Friday", "Saturday": "Saturday", "Sunday": "Sunday"}
STATES = {"positive": "positive", "neutral": "neutral", "negative": "negative", "not_classifiable": "not classifiable"}
HEADLINES = {"speed_component_positive": "Speed Positive", "deadline_component_positive": "Deadline Positive", "overall_strong": "Overall Status Strong",
             "overall_good": "Overall Status Good", "late_rate_below_peers": "late rate below the other Editors'"}
DIRECTION_WORDS = {"longer": "longer", "shorter": "shorter"}


def _reasons(params: Params) -> str:
    return ", ".join(f"{num(key)} {num(value)}" for key, value in params.get("reasons", {}).items())


def _value(p: Params) -> str:
    return f"{DIMENSIONS.get(p['dimension'], p['dimension'])} = {VALUES.get(str(p['value']), str(p['value']))}"


def _concentrated_group(p: Params) -> str:
    return types(p) if p["dimension"] == "video_type" else num(p["group"])


DATA = {
    "unattributed_projects": lambda p: (f"{num(p['projects'])} of {num(p['completed'])} completed projects have no verified Editor and are excluded from every "
                                        f"Editor finding ({_reasons(p)})."),
    "deadline_not_classifiable": lambda p: (f"{num(p['projects'])} of {num(p['attributed'])} attributed projects cannot be classified for deadline ({_reasons(p)}); "
                                            "no time is ever guessed."),
    "eta_observed_after_work_started": lambda p: (f"In {num(p['projects'])} of {num(p['attributed'])} attributed projects the Requested ETA used for the deadline "
                                                  "was first recorded after work had started."),
    "unknown_status_spans": lambda p: (f"{num(p['visits'])} status visits on {num(p['items'])} items contain a retired or cleared status and are not assigned "
                                       f"to any stage; {num(p['cycles_excluded_from_metrics'])} cycles are excluded from metrics for this reason."),
    "label_fact_disagreement": lambda p: (f"{num(p['late_label_on_not_late'])} projects carry {mon('Late Delivery')} although the first Ready For Approval was "
                                          f"on or before the ETA, {num(p['on_time_label_on_late'])} carry {mon('On Time Delivery')} although computed late, and "
                                          f"{num(p['late_without_late_label'])} computed-late projects carry no {mon('Late Delivery')} label."),
    "video_type_not_benchmark_eligible": lambda p: (f"{num(p['projects'])} projects have a Video Type that is not benchmark-eligible "
                                                    f"({', '.join(f'{mon(k)}: {num(v)}' for k, v in p['video_types'].items())}), so they get no speed comparison."),
}


def _check_text(code: str, p: Params) -> str:
    texts: dict[str, Callable[[Params], str]] = {
        "speed_competitive": lambda r: (f"execution speed is competitive: under the approved Speed rule over the whole history the reading is "
                                        f"{STATES.get(str(r.get('state')), str(r.get('state')))} (faster {num(r['weights']['faster'])}, similar "
                                        f"{num(r['weights']['similar'])}, slower {num(r['weights']['slower'])} projects)"),
        "late_cluster_in_short_runway": lambda r: (f"{num(r['short_runway_late'])} of {num(r['late'])} late projects started with less runway than typical "
                                                   f"execution needs, against {num(r['short_runway_not_late'])} of {num(r['not_late'])} projects that were not late"),
        "late_despite_typical_execution": lambda r: (f"{num(r['projects'])} of {num(r['late'])} late projects were executed within the other Editors' typical "
                                                     "time for the Video Type"),
        "peers_as_late_on_same_mix": lambda r: (f"on the same mix of Video Types the other Editors would be late {pct(r.get('expected_rate'))} of the time against "
                                                f"{pct(r.get('observed_rate'))} observed, so the gap that remains after the mix is below the material difference"),
        "eta_passed_before_start": lambda r: f"{plural(r['projects'], 'late project')} had already passed the ETA when work started",
        "negative_labels_rising": lambda r: (f"the share of projects with a scored Negative label rose from {pct(r['comparison'])} ({num(r['comparison_sample'])} "
                                             f"projects) to {pct(r['current'])} ({num(r['current_sample'])} projects)"),
        "negative_labels_behind_good_speed": lambda r: (f"{num(r['occurrences'])} scored Negative labels sit on {num(r['projects'])} current-window projects "
                                                        "despite a Positive Speed component"),
        "workload_above_own_history": lambda r: (f"median concurrent workload at start is {num(r['current_median'])} in the current window against "
                                                 f"{num(r['history_median'])} in the Editor's own history"),
        "late_rate_rising_behind_good_speed": lambda r: f"the late rate rose from {pct(r['comparison'])} to {pct(r['current'])} while Speed is Positive",
    }
    row = _checks(p, code)
    return texts[code](row) if row else ""


# One renderer per statement code. Each returns one sentence built only from the params.
T: dict[str, Callable[[Params], str]] = {
    # concentration
    "outcome_concentrated": lambda p: (f"{_concentrated_group(p)} accounts for {pct(p['outcome_share'])} of {OUTCOME_NAMES[p['outcome']]} "
                                       f"({num(p['group_outcomes'])} of {num(p['population_outcomes'])}) but {pct(p['population_share'])} of projects "
                                       f"({num(p['group_projects'])} of {num(p['population_projects'])}); its rate is {pct(p['group_rate'])} against "
                                       f"{pct(p['population_rate'])} overall" + (" (this month is still in progress)" if p.get("partial_period") else "") + "."),
    "editor_outcome_concentrated": lambda p: (f"{num(p['group_outcomes'])} of {who(p)}'s {num(p['population_outcomes'])} {OUTCOME_NAMES[p['outcome']]} are in "
                                              f"{_concentrated_group(p)}, which is {pct(p['population_share'])} of the Editor's projects ({num(p['group_projects'])} "
                                              f"of {num(p['population_projects'])})."),
    "concentration_suggests_group_level_factor": lambda p: "This suggests something about this group's work itself, not only the people doing it, is worth understanding.",
    "editor_outcomes_sit_in_group": lambda p: (f"This points to where the Editor's {OUTCOME_NAMES[p['outcome']]} occur; it compares the Editor only with their "
                                               "own project mix."),
    "group_may_differ_in_difficulty_or_scheduling": lambda p: ("This group may differ in scope, brief or scheduling in ways Monday does not record; this may "
                                                               "warrant checking."),
    "favourable_outcomes_sit_in_group": lambda p: "Favourable outcomes are over-represented in this group; this may show what works well there.",
    "significance_concentration": lambda p: "Where outcomes concentrate tells management where to look first, instead of reading team-wide averages.",
    "investigate_concentrated_group": lambda p: f"Review the {num(p['group_projects'])} projects behind this figure before drawing a conclusion.",
    # workflow / bottlenecks
    "phase_time_medians": lambda p: "Median elapsed time by phase: " + "; ".join(
        f"{PHASES.get(name, name)} {hrs(value['median_hours'])} ({plural(value['n'], 'project')})" for name, value in p["phases"].items()) + ".",
    "largest_median_phase": lambda p: (f"The longest phase by median is {PHASES.get(p['largest_median_phase'], p['largest_median_phase'])}; spans with retired "
                                       "statuses or still open are excluded."),
    "significance_time_map": lambda p: "Knowing where elapsed time goes separates Editor execution from waiting before and after it.",
    "investigate_largest_phase": lambda p: f"Look at the {PHASES.get(p['largest_median_phase'], p['largest_median_phase'])} phase first when discussing delivery time.",
    "late_projects_with_short_runway": lambda p: (f"{num(p['short_runway_late'])} of {num(p['late'])} late projects ({pct(p['share_of_late_with_short_runway'])}) "
                                                  "entered In Progress with less time before the Requested ETA than the other Editors' typical execution time "
                                                  "for that Video Type."),
    "short_runway_associated_with_lateness": lambda p: (f"Short runway is associated with lateness in this sample: {pct(p['short_runway_late_rate'])} of "
                                                        f"{num(p['short_runway'])} short-runway projects were late against {pct(p['adequate_runway_late_rate'])} of "
                                                        f"{num(p['adequate_runway'])} with adequate runway."),
    "eta_passed_before_work_started": lambda p: f"{num(p['late_with_eta_passed_at_start'])} late projects had already passed their Requested ETA when In Progress began.",
    "lateness_may_begin_before_editor_execution": lambda p: "This suggests that part of the lateness may begin before the Editor's work starts, not only during it.",
    "upstream_scheduling_or_eta_setting": lambda p: "How projects are scheduled, or how Requested ETAs are set, may warrant checking (D46).",
    "significance_pre_editor": lambda p: "Judging Editors on late rate alone would miss time that was never available to them.",
    "inspect_upstream_scheduling": lambda p: f"Inspect upstream scheduling for the {num(p['short_runway_late'])} late short-runway projects.",
    "on_time_submissions_delivered_after_eta": lambda p: (f"{num(p['delivered_after_eta'])} of {num(p['submitted_on_or_before_eta_and_delivered'])} projects "
                                                          "submitted for approval on or before the Requested ETA were delivered after it (median review wait "
                                                          f"{hrs(p['median_review_wait_hours'])}, median submission to delivery "
                                                          f"{hrs(p['median_submission_to_delivery_hours'])})."),
    "late_label_on_on_time_submission": lambda p: (f"{num(p['late_delivery_label_on_on_time_submission'])} of these carry a {mon('Late Delivery')} label although "
                                                   "the Editor submitted on time."),
    "delay_after_editor_interval_not_editor_execution": lambda p: "This delay happens after the Editor's interval ends, so it is not Editor execution time.",
    "review_or_delivery_stage_may_add_delay": lambda p: "The review or delivery stage may warrant checking; Monday does not show who holds the project then.",
    "significance_post_editor": lambda p: "A late client delivery can start after an on-time Editor submission; lateness labels should reflect that.",
    "inspect_review_and_delivery": lambda p: f"Review the approval and delivery steps for the {num(p['delivered_after_eta'])} projects.",
    # changes
    "late_rate_changed": lambda p: _change_rate(p),
    "negative_label_rate_changed": lambda p: _change_rate(p),
    "median_execution_changed": lambda p: (f"{(who(p) + chr(39) + 's') if p.get('editor_id') else 'Team'} median execution time in {types(p)} is "
                                           f"{hrs(p['current_hours'])} in the last {num(30)} completed days ({plural(p['current_sample'], 'project')}) against "
                                           f"{hrs(p['baseline_hours'])} in {'their own earlier history' if p.get('editor_id') else 'earlier history'} "
                                           f"({plural(p['baseline_sample'], 'project')}), {abs_pct(p['pct_change'])} "
                                           f"{'slower' if p['pct_change'] > 0 else 'faster'}."),
    "change_improving": lambda p: f"This is an improvement of at least the material difference ({_material(p)}).",
    "change_deteriorating": lambda p: f"This is a deterioration of at least the material difference ({_material(p)}).",
    "change_differs_from_team": lambda p: ("The change differs from the rest of the team's change over the same periods by at least the material difference, "
                                           "so it is more likely specific to this Editor."),
    "team_comparison_unavailable": lambda p: (f"The other Editors' change over the same periods cannot be measured at the approved sample minimums "
                                              f"({num(p.get('team_current_sample'))} and {num(p.get('team_baseline_sample'))} projects), so Atlas cannot tell "
                                              "whether this change is specific to this Editor."),
    "change_is_group_wide": lambda p: (f"{num(p['editors_same_direction'])} of {num(p['editors_with_both_periods'])} Editors with at least "
                                        f"{num(p['minimum_projects_per_editor'])} projects in both periods moved the same way. This pattern appears across "
                                        "multiple Editors and is more consistent with a shared workflow pattern than an isolated Editor pattern."),
    "change_breadth_not_established": lambda p: (f"Only {num(p['editors_same_direction'])} of {num(p['editors_with_both_periods'])} Editors with at least "
                                                  f"{num(p['minimum_projects_per_editor'])} projects in both periods moved the same way, so Atlas does not call "
                                                  "this change shared across Editors."),
    "workload_higher_in_same_period": lambda p: (f"Concurrent workload was also higher in the same period (median {num(p['workload_median_current'])} against "
                                                 f"{num(p['workload_median_baseline'])}); the two are associated here, which is not proof of cause."),
    "team_moved_the_same_way": lambda p: ("The rest of the team changed by a similar amount over the same periods"
                                          + (f" ({signed_pct(p['team_pct_change'])})" if p.get("team_pct_change") is not None else "")
                                          + ", so this change mirrors the team and is unlikely to be specific to this Editor."),
    "change_needs_context_before_conclusion": lambda p: ("A change against a baseline may reflect project mix, workload or scheduling; this may warrant "
                                                         "checking before any conclusion."),
    "significance_change": lambda p: "A material change from the usual pattern is an early point for a conversation, not a verdict.",
    "investigate_change": lambda p: (f"Compare the {num(p['current_sample'])} recent projects with the {num(p['baseline_sample'])} baseline projects for Video "
                                     "Type, runway and workload."),
    # workload
    "workload_bands": lambda p: (f"Projects are placed in a higher or lower workload band by comparing the Editor's other open projects at start with that "
                                 f"Editor's own median ({num(p.get('higher_band_projects', p.get('higher_band')))} higher, "
                                 f"{num(p.get('lower_band_projects', p.get('lower_band')))} lower)."),
    "higher_workload_associated_with_execution_time": lambda p: (f"Higher concurrent workload is associated with {DIRECTION_WORDS[p['direction']]} execution "
                                                                 f"in this sample: the median difference across {num(p['strata'])} Editor x Video Type groups is "
                                                                 f"{abs_pct(p['median_stratum_pct'])}, and {num(p['strata_longer_when_higher'])} of "
                                                                 f"{num(p['strata'])} groups point the same way."),
    "higher_workload_associated_with_late_rate": lambda p: (f"Higher concurrent workload is associated with a {'higher' if p['difference'] > 0 else 'lower'} late "
                                                            f"rate in this sample: {pct(p['higher_rate'])} of {num(p['higher_band'])} against "
                                                            f"{pct(p['lower_rate'])} of {num(p['lower_band'])}."),
    "higher_workload_associated_with_negative_label_rate": lambda p: (f"Higher concurrent workload is associated with a "
                                                                      f"{'higher' if p['difference'] > 0 else 'lower'} share of projects with Negative labels: "
                                                                      f"{pct(p['higher_rate'])} against {pct(p['lower_rate'])}."),
    "association_not_cause_workload": lambda p: "Workload and the outcome move together here, which is not proof of cause (elapsed time includes parallel work).",
    "workload_may_contribute": lambda p: "Concurrent assignments may warrant checking as one possible contributor.",
    "significance_workload": lambda p: "If outcomes worsen when work piles up, assignment volume is a lever management controls.",
    "compare_assignment_volume": lambda p: "Compare recent assignment volume with the Editor's historical workload.",
    # patterns
    "late_delivery_elevated_across_editors": lambda p: (f"Late delivery is higher inside {types(p)} than outside it for {num(p['elevated_editors'])} of "
                                                        f"{num(p['qualifying_editors'])} Editors with enough projects in both."),
    "short_runway_elevated_across_editors": lambda p: (f"Projects in {types(p)} start with short runway more often than the same Editor's other projects for "
                                                       f"{num(p['elevated_editors'])} of {num(p['qualifying_editors'])} qualifying Editors."),
    "pattern_appears_process_wide": lambda p: ("This pattern appears across multiple Editors and is more consistent with a shared workflow pattern than an "
                                               "isolated Editor pattern."),
    "shared_workflow_or_type_factor": lambda p: "A shared workflow or Video Type-specific factor may warrant checking.",
    "late_delivery_elevated_for_one_editor_only": lambda p: (f"Among {num(p['qualifying_editors'])} qualifying Editors, only {mon(p.get('confined_editor_name'))} "
                                                             f"is late more often inside {types(p)} than outside it."),
    "short_runway_elevated_for_one_editor_only": lambda p: (f"Among {num(p['qualifying_editors'])} qualifying Editors, only {mon(p.get('confined_editor_name'))} "
                                                            f"receives {types(p)} projects with short runway more often than their other work."),
    "pattern_confined_to_one_editor": lambda p: "The pattern is confined to one Editor in this Video Type rather than shared.",
    "runway_pattern_is_upstream_context": lambda p: "Runway is set before the Editor starts, so this is context about the work received, not about the Editor's execution.",
    "assignment_or_scheduling_for_this_editor": lambda p: "How this Video Type is scheduled or assigned to this Editor may warrant checking.",
    "editor_specific_factor_possible": lambda p: "An Editor-specific factor is possible and may warrant a conversation; the data does not identify it.",
    "working_practice_worth_understanding": lambda p: ("How this Editor plans or sequences comparable work may be worth understanding and sharing; the data "
                                                       "does not identify it."),
    "significance_shared": lambda p: "A shared pattern points to process or scheduling, not to one person.",
    "significance_confined_late_delivery": lambda p: "A pattern confined to one Editor is worth a specific, evidence-based conversation.",
    "significance_confined_short_runway": lambda p: "Short runway concentrated on one Editor's work changes how that Editor's late rate should be read.",
    "review_shared_workflow": lambda p: "Review the shared workflow for this Video Type across the affected Editors.",
    "review_confined_late_delivery": lambda p: "Review this Editor's projects in this Video Type with the evidence before concluding.",
    "review_confined_short_runway": lambda p: "Review how this Video Type is scheduled for this Editor.",
    "repeated_delay_combination": lambda p: (f"{types(p)} projects with {_value(p)} were late {pct(p['late_rate'])} of the time ({num(p['late'])} of "
                                             f"{num(p['projects'])}) against {pct(p['overall_late_rate'])} for all projects of this Video Type "
                                             f"({num(p['video_type_projects'])}); {num(p['cells_tested'])} combinations were tested."),
    "combination_repeats_over_time": lambda p: "The combination was elevated in both the earlier and the later half of the history, so it is not a one-off.",
    "combination_may_mark_process_risk": lambda p: "This combination may mark a process risk that warrants checking.",
    "significance_repeated_delay": lambda p: "A repeated combination is more actionable than an average: it names the situation to avoid.",
    "review_combination": lambda p: f"Review how projects of this Video Type with {_value(p)} are planned.",
    "same_label_repeats_across_editors": lambda p: (f"{mon(p['label'])} appears {num(p['occurrences'])} times on {types(p)} projects across {num(p['editors'])} "
                                                    f"Editors ({num(p['type_projects'])} projects of this Video Type in total)."),
    "label_pattern_not_one_editor": lambda p: "The same label recurs across several Editors, so it is unlikely to be about one person only.",
    "type_brief_or_process_may_drive_label": lambda p: "The brief or process for this Video Type may warrant checking.",
    "significance_repeated_quality": lambda p: "A label that repeats across Editors points to a shared cause worth finding.",
    "review_label_in_type": lambda p: f"Review the {num(p['occurrences'])} occurrences of this label on projects of this Video Type together.",
    "time_bucket_elevated": lambda p: (f"Projects with {_value(p)} were late {pct(p['late_rate'])} of the time against {pct(p['overall_late_rate'])} that their "
                                       f"Video Types predict, elevated in {num(p['months_elevated'])} of {num(p['months_tested'])} months."),
    "timing_pattern_repeats": lambda p: "The timing effect repeats across months rather than appearing once.",
    "timing_may_reflect_scheduling": lambda p: "Scheduling around this period may warrant checking.",
    "significance_time_pattern": lambda p: "A repeating timing pattern can be planned around.",
    "review_timing": lambda p: "Review how work is scheduled in this period.",
    # person vs system
    "mix_adjusted_late_rate": lambda p: (f"On the same mix of Video Types, the other Editors' rates predict {num(p['expected_late'])} late projects out of "
                                         f"{num(p['covered_projects'])} ({pct(p['expected_rate'])}); {who(p)} had {num(p['observed_late'])} "
                                         f"({pct(p['observed_rate'])})."),
    "editor_differs_from_peers_on_same_mix": lambda p: f"The Editor's late rate differs from what the same mix predicts by {pp(p['excess'])}.",
    "same_conditions_late_rate": lambda p: (f"Compared under similar runway as well, the difference is {pp((p['same_conditions'] or {}).get('excess'))} "
                                            f"({plural((p['same_conditions'] or {}).get('covered_projects') or 0, 'project')})."),
    "difference_persists_after_mix": lambda p: "The difference persists after accounting for the Video Types the Editor worked on.",
    "better_than_peers_after_mix": lambda p: "The Editor is late less often than the same mix predicts.",
    "raw_late_rate_gap": lambda p: f"{who(p)}'s raw late rate is {pct(p['raw_editor_rate'])} against {pct(p['raw_peer_rate'])} for the other Editors.",
    "raw_gap_largely_reflects_work_mix": lambda p: (f"Most of that gap ({pct(p['share_of_gap_explained_by_mix'])}) reflects the mix of Video Types the Editor "
                                                    "worked on, not a difference on comparable work."),
    "adjusted_gap_just_below_material": lambda p: (f"After accounting for the Video Type mix the gap is {pp(p['excess'])}, just below the material difference; the "
                                                   f"mix explains only {pct(p['share_of_gap_explained_by_mix'])} of it."),
    "check_assignment_mix": lambda p: "The assignment mix may warrant checking before comparing Editors on late rate.",
    "gap_remains_worth_review": lambda p: "The remaining gap is close to material and may warrant review with the project evidence.",
    "significance_editor_specific": lambda p: ("A difference that survives the mix adjustment is more likely to be about the individual, and is worth a "
                                               "specific, evidence-based conversation."),
    "significance_mix_explains": lambda p: "The raw late-rate comparison would mislead here; the work mix explains most of it.",
    "significance_adjusted_gap_below_material": lambda p: "The raw comparison overstates the gap only slightly; the adjusted figure is the fairer one to discuss.",
    "review_editor_specific_deadline": lambda p: "Review the Editor's late projects in the listed Video Types with their runway and workload.",
    "review_assignment_mix": lambda p: "Review how Video Types are distributed to this Editor compared with the team.",
    # contradictions
    "conflict_fast_but_late": lambda p: f"{who(p)}'s Speed component is Positive while the Deadline component is Negative in the same window.",
    "conflict_slow_but_on_time": lambda p: f"{who(p)}'s Speed component is Negative while the Deadline component is Positive in the same window.",
    "conflict_better_than_team_but_mostly_late": lambda p: (f"{who(p)}'s Deadline component is Positive (better than the other Editors) while "
                                                            f"{num(p['late'])} of {num(p['deadline_classifiable_projects'])} of their own projects are late "
                                                            f"({pct(p['absolute_late_rate'])})."),
    "components_disagree_do_not_collapse": lambda p: ("The evidence is mixed: the components point in different directions and are shown side by side instead of "
                                                      "being merged into one reading."),
    "conflict_points_outside_execution": lambda p: "When speed and deadline disagree, the explanation may lie outside execution (runway, scheduling) and may warrant checking.",
    "significance_metric_conflict": lambda p: "A single status would hide this conflict; the manager should see both sides.",
    "investigate_conflict": lambda p: "Investigate whether the late projects concentrate in specific Video Types, workload periods or short runway.",
    "headline_late_rate_above_peers": lambda p: (f"{who(p)}'s late rate over the ingested history is {pct(p['late_rate'])} ({num(p['late'])} of "
                                                 f"{num(p['deadline_classifiable_projects'])}) against {pct(p['peer_late_rate'])} for the other Editors."),
    "check_speed_competitive": lambda p: "However, " + _check_text("speed_competitive", p) + ".",
    "check_late_cluster_in_short_runway": lambda p: "Also, " + _check_text("late_cluster_in_short_runway", p) + ".",
    "check_late_despite_typical_execution": lambda p: "Also, " + _check_text("late_despite_typical_execution", p) + ".",
    "check_peers_as_late_on_same_mix": lambda p: "Also, " + _check_text("peers_as_late_on_same_mix", p) + ".",
    "check_eta_passed_before_start": lambda p: "Also, " + _check_text("eta_passed_before_start", p) + ".",
    "headline_may_overstate_execution_cause": lambda p: ("The evidence is mixed: the headline deadline result is weak, but execution-speed evidence does not "
                                                         "support a simple speed explanation. This does not show the Editor has no part in the late outcomes."),
    "lateness_may_arise_outside_execution": lambda p: "Part of the lateness may arise before or around execution (runway, Video Type, workload) and may warrant checking.",
    "significance_bad_headline": lambda p: "Do not stop at the headline late rate when discussing this Editor.",
    "investigate_before_concluding_speed": lambda p: ("Investigate whether the Editor's late outcomes concentrate in specific Video Types, workload periods or "
                                                      "short ETA runway before concluding that execution speed is the primary issue."),
    "favourable_headline": lambda p: f"{who(p)}'s headline looks favourable ({', '.join(HEADLINES.get(item, item) for item in p['favourable_headline'])}).",
    "check_negative_labels_rising": lambda p: "However, " + _check_text("negative_labels_rising", p) + ".",
    "check_negative_labels_behind_good_speed": lambda p: "However, " + _check_text("negative_labels_behind_good_speed", p) + ".",
    "check_workload_above_own_history": lambda p: "Also, " + _check_text("workload_above_own_history", p) + ".",
    "check_late_rate_rising_behind_good_speed": lambda p: "However, " + _check_text("late_rate_rising_behind_good_speed", p) + ".",
    "good_headline_hides_signal": lambda p: "The evidence is mixed: a favourable headline may be hiding an early signal in another measurement.",
    "early_signal_worth_review": lambda p: "This may warrant an early look before it shows in the headline.",
    "significance_hidden_risk": lambda p: "Good headlines are rarely re-examined; this one has a signal worth checking.",
    "review_hidden_signal": lambda p: "Review the current-window projects listed in the evidence.",
    # risks
    "risk_past_eta": lambda p: _risk(p),
    "risk_short_remaining_runway": lambda p: _risk(p),
    "risk_elapsed_beyond_typical": lambda p: _risk(p),
    "risk_editor_workload_above_own_high_percentile": lambda p: _risk(p),
    "risk_review_wait_beyond_typical": lambda p: _risk(p),
    "risk_signal_deserves_attention": lambda p: "This is a risk signal that deserves attention now, while the work is still open.",
    "risk_signal_not_prediction": lambda p: ("These projects currently have risk signals that resemble historically difficult conditions; this is not a "
                                             "prediction of their outcome."),
    "significance_open_risk": lambda p: "Open work can still be helped; history cannot.",
    "check_open_past_eta": lambda p: "Check the listed projects now and agree a realistic delivery time.",
    "check_open_short_remaining_runway": lambda p: "Check whether the listed projects can realistically meet their Requested ETA.",
    "check_open_elapsed_beyond_typical": lambda p: "Check what is holding the listed projects.",
    "check_open_editor_workload_above_own_high_percentile": lambda p: "Check whether new assignments to these Editors can wait.",
    "check_open_review_wait_beyond_typical": lambda p: "Check the approval queue for the listed projects.",
    "open_project_runway": lambda p: (f"Open {types(p)} project {num(p['monday_item_id'])} ({mon(p['editor_name']) if p.get('editor_name') else 'Editor unresolved'}) "
                                      f"started with {hrs(p['runway_hours'])} of runway against a typical execution time of {hrs(p['typical_hours'])}."),
    "resembles_historical_projects": lambda p: (f"It resembles {num(p['similar_projects'])} historical projects of this Video Type with "
                                                f"{VALUES.get(p['runway_band'], p['runway_band'])} runway, {num(p['similar_late'])} of which "
                                                f"({pct(p['similar_late_rate'])}) were late, against {pct(p['video_type_late_rate'])} for the Video Type overall."),
    "base_rate_not_prediction": lambda p: "This is a historical base rate, not a prediction for this project.",
    "significance_similarity": lambda p: "The situation this project is in has historically gone badly more often than usual.",
    "check_open_project": lambda p: f"Check project {num(p['monday_item_id'])} while it is still open.",
    # editor
    "speed_faster_than_comparable_team": lambda p: _speed(p, "faster"),
    "speed_slower_than_comparable_team": lambda p: _speed(p, "slower"),
    "speed_pattern_within_video_type": lambda p: "Each comparison stays inside one exact Video Type and excludes the Editor from the benchmark (D36).",
    "check_context_before_speed_conclusion": lambda p: "Workload, runway and project mix may warrant checking before treating this as a speed issue.",
    "significance_speed_faster": lambda p: "Consistent speed within a Video Type across a sufficient sample is an evidence-based strength.",
    "significance_speed_slower": lambda p: "A slower reading within a Video Type is a specific point to understand, not a general judgement.",
    "review_speed_context": lambda p: "Review the slower Video Types with the workload and runway context below.",
    "recognise_evidence": lambda p: "Share the evidence with the Editor; it is specific and verifiable.",
    "negative_signals_concentrated_in_deadline": lambda p: (f"{num(p['top_count'])} of {who(p)}'s {num(p['occurrences'])} Negative signals are "
                                                            f"{mon(p['top_label'])}, so the negative evidence is concentrated in deadline performance rather "
                                                            "than broad quality problems."),
    "negative_label_distribution": lambda p: (f"The most frequent Negative label on {who(p)}'s projects is {mon(p['top_label'])} ({num(p['top_count'])} of "
                                              f"{num(p['occurrences'])})."),
    "positive_label_distribution": lambda p: (f"The most frequent Positive label on {who(p)}'s projects is {mon(p['top_label'])} ({num(p['top_count'])} of "
                                              f"{num(p['occurrences'])})."),
    "negative_label_pattern_meaning": lambda p: "Labels are hand-applied, so these counts are a lower bound and say where management noticed problems.",
    "positive_label_pattern_meaning": lambda p: "Positive labels are hand-applied recognition; they show where management noticed good work.",
    "check_label_pattern_by_type_and_workload": lambda p: "Whether these labels concentrate in specific Video Types, workload periods or short runway may warrant checking.",
    "significance_negative_labels": lambda p: "Knowing which issue dominates focuses the conversation on one area instead of a general impression.",
    "significance_positive_labels": lambda p: "Specific recognition is more useful than a general impression.",
    "review_label_pattern": lambda p: f"Review the {num(p['projects'])} labelled projects listed in the evidence.",
    # data
    "data_state_not_performance": lambda p: "This is a data state, not a performance result; affected projects are excluded or flagged, never guessed.",
}
for _code, _render in DATA.items():
    T[f"data_{_code}"] = _render
    T[f"significance_data_{_code}"] = lambda p: "Findings exclude these projects; their volume shows how much of the operation the analysis can see."
    T[f"fix_data_{_code}"] = lambda p: "Fix the source data in Monday where possible; Atlas will include the projects once the evidence exists."


def _change_rate(p: Params) -> str:
    subject = f"{who(p)}'s" if p.get("editor_id") else "The team's"
    against = (AGAINST if p.get("editor_id") else AGAINST_TEAM)[p["against"]]
    text = (f"{subject} {MEASURE_NAMES[p['measure']]} is {pct(p['current'])} in the last {num(30)} completed days ({plural(p['current_sample'], 'project')}) "
            f"against {pct(p['baseline'])} in {against} ({plural(p['baseline_sample'], 'project')}), a change of {pp(p['difference'])}.")
    if p.get("editor_id") and p.get("team_current") is not None:
        text += f" Over the same periods the other Editors went from {pct(p['team_baseline'])} to {pct(p['team_current'])}."
    return text


def _risk(p: Params) -> str:
    items = ", ".join(f"{num(row['monday_item_id'])} ({mon(row['status'])}{', ' + mon(row['editor_name']) if row.get('editor_name') else ''})"
                      for row in p["items"][:10])
    more = f" and {num(len(p['items']) - 10)} more" if len(p["items"]) > 10 else ""
    return f"{plural(p['projects'], 'open project')} {SIGNALS[p['signal']]} at {num(p['retrieved_at'])}: {items}{more}."


def _speed(p: Params, verdict: str) -> str:
    rows = "; ".join(f"{' + '.join(mon(label) for label in row['labels'])}: {hrs(row['editor_median_hours'])} over {plural(row['editor_projects'], 'project')} "
                     f"against {hrs(row['comparator_median_hours'])} for {plural(row['comparator_projects'], 'project')} of {num(row['comparator_editors'])} other "
                     f"Editors ({signed_pct(row['pct'])})" for row in p["video_types"])
    return f"{who(p)} is {verdict} than the comparable team in the current window under the approved Speed rule: {rows}."


def _p(finding: Any) -> Params:
    return finding.statements[0].params


def _first_upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def _measure_title(p: Params) -> str:
    return {"late_rate": "late rate", "negative_label_rate": "Negative label rate"}.get(p.get("measure", ""), f"execution time in {types(p)}")


def _pattern_measure(p: Params) -> str:
    return "short runway" if p["measure"] == "short_runway" else "late delivery"


# Every title names its subject (the Editor, the Video Type or the project) so a card is understandable on its own.
TITLES: dict[str, Callable[[Any], str]] = {
    "concentration.negative": lambda f: (f"{_first_upper(OUTCOME_NAMES[_p(f)['outcome']])} concentrate in {_concentrated_group(_p(f))}" if not f.scope.editor_id
                                         else f"{who(_p(f))}: {OUTCOME_NAMES[_p(f)['outcome']]} concentrate in {_concentrated_group(_p(f))}"),
    "concentration.positive": lambda f: (f"{_first_upper(OUTCOME_NAMES[_p(f)['outcome']])} concentrate in {_concentrated_group(_p(f))}" if not f.scope.editor_id
                                         else f"{who(_p(f))}: {OUTCOME_NAMES[_p(f)['outcome']]} concentrate in {_concentrated_group(_p(f))}"),
    "workflow.time_map": lambda f: "Where project time goes",
    "bottleneck.pre_editor_runway": lambda f: "Late projects often start with too little runway",
    "bottleneck.post_editor": lambda f: "Delay after on-time submission",
    "change.editor": lambda f: f"{who(_p(f))}: {_measure_title(_p(f))} {'improved' if f.direction == 'favourable' else 'worsened'} against own history",
    "change.team": lambda f: f"Team {MEASURE_NAMES[_p(f)['measure']]} {'improved' if f.direction == 'favourable' else 'worsened'}",
    "change.video_type": lambda f: (f"{types(_p(f))}: execution time {'improved' if f.direction == 'favourable' else 'worsened'}"
                                    + (" across Editors" if _p(f).get("shared_across_editors") else "")),
    "workload.association": lambda f: "Workload moves with outcomes across the team",
    "workload.overload_pattern": lambda f: f"{who(_p(f))}: higher workload coincides with {'worse' if f.direction == 'adverse' else 'better'} outcomes",
    "pattern.shared_across_editors": lambda f: (f"{types(_p(f))}: {_pattern_measure(_p(f))} is more common across Editors" if f.category == "system_pattern"
                                                else f"{types(_p(f))}: {_pattern_measure(_p(f))} pattern confined to {mon(_p(f).get('confined_editor_name'))}"),
    "pattern.repeated_delay": lambda f: f"{types(_p(f))}: repeated delay when {_value(_p(f))}",
    "pattern.repeated_quality": lambda f: f"{types(_p(f))}: {mon(_p(f)['label'])} recurs across Editors",
    "pattern.time": lambda f: f"Repeating timing pattern: {_value(_p(f))}",
    "person.mix_adjusted_deadline": lambda f: {"editor_specific_pattern": f"{who(_p(f))}: late rate differs from peers on the same work",
                                               "hidden_context": f"{who(_p(f))}: work mix and the late-rate headline"}[f.category],
    "contradiction.metric_conflict": lambda f: f"{who(_p(f))}: speed and deadline point different ways",
    "contradiction.bad_headline": lambda f: f"{who(_p(f))}: the late-rate headline needs context",
    "contradiction.hidden_risk": lambda f: f"{who(_p(f))}: a good headline hides a signal",
    "risk.open_work": lambda f: f"Open work: {plural(_p(f)['projects'], 'project')} {SIGNALS[_p(f)['signal']]}",
    "risk.historical_similarity": lambda f: f"Open project {num(_p(f)['monday_item_id'])} resembles historically late work",
    "editor.speed_pattern": lambda f: f"{who(_p(f))}: {'faster' if f.direction == 'favourable' else 'slower'} than the comparable team",
    "editor.label_pattern": lambda f: f"{who(_p(f))}: where {'Negative' if f.direction == 'adverse' else 'Positive'} labels sit",
}

DATA_TITLES = {"data.unattributed_projects": "Projects without a verified Editor", "data.deadline_not_classifiable": "Projects without a usable Requested ETA",
               "data.eta_observed_after_work_started": "Requested ETA set after work started", "data.unknown_status_spans": "Status spans with retired statuses",
               "data.label_fact_disagreement": "Labels that disagree with the computed deadline", "data.video_type_not_benchmark_eligible": "Video Types without a benchmark"}


def _fixed_title(title: str) -> Callable[[Any], str]:
    return lambda finding: title


for _type, _title in DATA_TITLES.items():
    TITLES[_type] = _fixed_title(_title)

QUESTIONS: dict[str, Callable[[Any, Params], str]] = {
    "bottleneck.pre_editor_runway": lambda f, p: "Why are these projects entering In Progress with less runway than their Video Type usually needs?",
    "bottleneck.post_editor": lambda f, p: "What happens between an on-time submission and delivery for these projects?",
    "change.editor": lambda f, p: "What changed for this Editor between the two periods: project mix, workload or scheduling?",
    "change.team": lambda f, p: "What changed in the team's operating conditions between the two periods?",
    "change.video_type": lambda f, p: "What changed in work of this Video Type recently?",
    "workload.association": lambda f, p: "Are assignments piling up at times that coincide with worse outcomes?",
    "workload.overload_pattern": lambda f, p: "What happens to this Editor's projects that start while more of their work is already open?",
    "pattern.shared_across_editors": lambda f, p: ("What about this Video Type makes this pattern appear across Editors?" if f.category == "system_pattern"
                                                   else "Why does this pattern appear only in one Editor's work of this Video Type?"),
    "pattern.repeated_delay": lambda f, p: "Why do projects in this combination keep ending late?",
    "pattern.repeated_quality": lambda f, p: "Why does this label recur on projects of this Video Type across Editors?",
    "pattern.time": lambda f, p: "Why is lateness higher in this period?",
    "person.mix_adjusted_deadline": lambda f, p: "On comparable work, what differs for this Editor?",
    "contradiction.metric_conflict": lambda f, p: "Why do this Editor's speed and deadline readings disagree?",
    "contradiction.bad_headline": lambda f, p: "Is this Editor's late rate about execution, or about the runway and work they received?",
    "contradiction.hidden_risk": lambda f, p: "Is the signal behind this Editor's good headline the start of a change?",
    "risk.open_work": lambda f, p: "Which of these open projects need a decision today?",
    "risk.historical_similarity": lambda f, p: "Can this project still be delivered on time?",
    "editor.speed_pattern": lambda f, p: "What explains this Editor's speed reading in these Video Types?",
    "editor.label_pattern": lambda f, p: "What is behind the labels on this Editor's projects?",
    "concentration.negative": lambda f, p: "What is different about work in this group?",
    "concentration.positive": lambda f, p: "What works well in this group that could be repeated?",
    "workflow.time_map": lambda f, p: "Which phase would most reduce delivery time if it were shorter?",
}
DEFAULT_QUESTION = "What would explain this pattern?"
DATA_QUESTION = "What would it take to capture this evidence in Monday?"

LIMITATIONS = {
    "elapsed_clock_time_not_effort": "Durations are elapsed clock time, not effort: nights, weekends and parallel work are included (D3).",
    "video_type_is_the_only_complexity_control": "Video Type is the only available control for complexity; length, footage and brief are not recorded.",
    "labels_are_hand_applied_lower_bound": "Labels are applied by hand, so label counts are a lower bound.",
    "association_not_causation": "This is an association in observational data, not proof of cause.",
    "concurrency_counts_attributed_completed_first_cycles_only": "Workload counts only attributed, completed first cycles, so it is a lower bound.",
    "unattributed_projects_excluded": "Projects without a verified Editor are excluded.",
    "some_etas_first_observed_after_work_started": "Some Requested ETAs were first recorded after work started.",
    "revision_cause_not_recorded": "Monday does not record why a revision happened.",
    "history_limited_to_ingest_window": "History starts at the ingest window (2026-02-01 in production).",
    "stage_owner_not_identifiable_shared_account": "Who held the project in this stage cannot be identified (shared Waset Co account).",
    "typical_execution_uses_whole_ingested_history": "Typical execution time uses the whole ingested history of other Editors in the same Video Type.",
    "not_adjusted_for_video_type_mix": "Not adjusted for the mix of Video Types.",
    "current_snapshot_only": "Based on the current Monday snapshot only.",
    "several_combinations_tested": "Several combinations were tested; some elevated cells can appear by chance, which is why repetition over time is required.",
    "no_evidence_of_actual_cause": "The data shows what happened, not why.",
    "includes_a_partial_period": "Includes a month still in progress.",
    "sample_near_minimum": "The sample is close to its minimum.",
    "uses_proposed_parameters_not_approved": "Uses proposed thresholds that management has not approved (review only).",
}

UNCERTAINTY = {
    ("strong", "association"): "Strong evidence of an association; it is still not proof of cause.",
    ("moderate", "association"): "Moderate evidence of an association in this sample.",
    ("weak", "association"): "Early indication of an association; the evidence is limited.",
    ("strong", "other"): "Strong evidence: the pattern holds across several independent slices.",
    ("moderate", "other"): "Moderate evidence.",
    ("weak", "other"): "Limited evidence: treat this as an early indication.",
    ("strong", "fact"): "A direct fact from the current Monday snapshot.",
    ("moderate", "fact"): "A direct fact from the current Monday snapshot.",
    ("weak", "fact"): "A direct fact from the current Monday snapshot.",
}
LEVEL_NAMES = {"weak": "Weak", "moderate": "Moderate", "strong": "Strong"}
FACTOR_NAMES = {"sample_size": "sample size", "replication": "replication", "contradicting_evidence": "contradicting evidence",
                "data_completeness": "data completeness", "independent_examples": "independent examples", "direct_observation": "direct observation"}
ASSESSMENTS = {"supports": "supports", "limits": "limits", "not_assessed": "not assessed", "information": "information"}
JOIN = "; "

LANGUAGE_RULES: dict[str, Any] = {
    "levels": {"fact": "stated plainly with counts", "metric": "stated with its formula and sample", "pattern": "'X of Y' with the comparison named",
               "association": "'is associated with ... in this sample'; never 'causes', 'because of' or 'leads to'",
               "interpretation": "'This suggests / points to ...'", "hypothesis": "'This may warrant checking ...'; a question, not a conclusion"},
    "insufficient_evidence": "There is not enough comparable history to classify this pattern.",
    "forbidden": ["causal verbs about people", "blame", "psychological or personality judgements", "HR, pay, promotion, disciplinary or termination recommendations",
                  "revisions as Editor fault", "a person behind the shared Waset Co account", "certainty about open work"],
    "uncertainty": {f"{level}/{kind}": text for (level, kind), text in UNCERTAINTY.items()},
}

# Tables every language module defines with exactly the same keys (tests compare them).
TABLES = ("T", "TITLES", "QUESTIONS", "LIMITATIONS", "UNCERTAINTY", "LEVEL_NAMES", "FACTOR_NAMES", "ASSESSMENTS", "OUTCOME_NAMES", "MEASURE_NAMES",
          "AGAINST", "AGAINST_TEAM", "SIGNALS", "PHASES", "DIMENSIONS", "VALUES", "STATES", "HEADLINES", "DIRECTION_WORDS", "DATA", "DATA_TITLES")


def module(lang: str) -> Any:
    """The narrative module of one language (``en`` is this module, ``ar`` is ``narrative_ar``)."""
    import sys
    if lang == "en":
        return sys.modules[__name__]
    if lang == "ar":
        from atlas_commander.investigation import narrative_ar
        return narrative_ar
    raise ValueError(f"unsupported narrative language {lang!r}")


def render(code: str, params: Params, lang: str = "en") -> str:
    table = module(lang).T
    if code not in table:
        raise KeyError(f"no narrative template for statement code {code!r}")
    return str(table[code](params)).strip()


def view(finding: Mapping[str, Any]) -> Any:
    """A finding document entry as an object with the attributes the title and question tables read (presentation only)."""

    def statement(row: Mapping[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(level=row["level"], code=row["code"], params=row["params"])

    return SimpleNamespace(
        finding_type=finding["finding_type"], category=finding["category"], direction=finding["direction"], scope=SimpleNamespace(**finding["scope"]),
        statements=[statement(row) for row in finding["statements"]], significance=statement(finding["significance"]),
        investigations=[statement(row) for row in finding["suggested_investigations"]],
        parameters=[SimpleNamespace(status=row["status"]) for row in finding["parameters"]], confidence=finding.get("confidence"),
        limitations=finding["limitations"])


def finding_text(finding: Any, lang: str = "en", *, marked: bool = False) -> dict[str, Any]:
    """Every management sentence for one finding, each from its structured fields (Task 47), in ``lang``.

    ``finding`` is an engine :class:`Finding` or a :func:`view` of a document entry. ``marked`` keeps the isolate marks (the site turns
    them into ``<bdi>``); the document stores the plain text."""
    lm = module(lang)

    def out(text: str) -> str:
        return text if marked else plain(text)

    def say(code: str, params: Params) -> str:
        if code not in lm.T:
            raise KeyError(f"no narrative template for statement code {code!r}")
        return str(lm.T[code](params)).strip()

    observed = [say(s.code, s.params) for s in finding.statements if s.level in (FACT, METRIC, PATTERN, ASSOCIATION)]
    interpretations = [say(s.code, s.params) for s in finding.statements if s.level == INTERPRETATION]
    hypotheses = [say(s.code, s.params) for s in finding.statements if s.level == HYPOTHESIS]
    params = finding.statements[0].params
    confidence = finding.confidence or {}
    levels = {s.level for s in finding.statements}
    kind = "association" if ASSOCIATION in levels else "fact" if FACT in levels and not ({METRIC, PATTERN} & levels) else "other"
    level = confidence.get("level", "weak")
    factors = [f"{lm.FACTOR_NAMES.get(factor['factor'], factor['factor'])}: {lm.ASSESSMENTS.get(factor['assessment'], factor['assessment'])}"
               for factor in confidence.get("factors", [])]
    limitations = [lm.LIMITATIONS[code] for code in sorted(set(finding.limitations))]
    if any(use.status != "approved" for use in finding.parameters):
        limitations.append(lm.LIMITATIONS["uses_proposed_parameters_not_approved"])
    question = (lm.DATA_QUESTION if finding.finding_type.startswith("data.")
                else lm.QUESTIONS.get(finding.finding_type, lambda f, p: lm.DEFAULT_QUESTION)(finding, params))
    return {
        "title": out(lm.TITLES[finding.finding_type](finding)),
        "summary": out(" ".join([*observed[:1], *interpretations[:1]])),
        "observation": out(" ".join(observed)),
        "interpretation": out(" ".join(interpretations)),
        "hypothesis": out(" ".join(hypotheses)),
        "management_significance": out(say(finding.significance.code, finding.significance.params)),
        "suggested_investigation": out(" ".join(say(s.code, s.params) for s in finding.investigations)),
        "investigation_question": out(question),
        "confidence_explanation": out(f"{lm.LEVEL_NAMES.get(level, level)}. " + lm.JOIN.join(factors) + "."),
        "limitations": limitations,
        "uncertainty": lm.UNCERTAINTY[(level, kind)],
    }


def executive_brief(findings: Sequence[Finding], ctx: Any) -> list[dict[str, Any]]:
    """The management brief (Task 51): one entry per top finding answering what, unusual, where, evidence, why and next."""
    brief = []
    for finding in findings:
        text = finding.text or finding_text(finding)
        where = []
        labels = {p.cohort_key: " + ".join(p.cohort_labels) for p in ctx.facts.projects if p.cohort_key and p.cohort_labels}
        if finding.affected_video_types:
            names = [labels.get(key, key) for key in finding.affected_video_types]
            where.append(f"Video Types: {', '.join(names[:6])}" + (f" and {len(names) - 6} more" if len(names) > 6 else ""))
        if finding.affected_editors:
            where.append(f"Editors: {', '.join(ctx.name(editor) or editor for editor in finding.affected_editors[:6])}"
                         + (f" and {len(finding.affected_editors) - 6} more" if len(finding.affected_editors) > 6 else ""))
        unusual = next((plain(render(s.code, s.params)) for s in finding.statements if s.level in (PATTERN, ASSOCIATION)), text["observation"])
        brief.append({
            "finding_id": finding.finding_id,
            "title": text["title"],
            "what_happened": text["summary"],
            "is_it_unusual": unusual,
            "where": "; ".join(where) or "Team-wide",
            "evidence": (f"{plain(plural(finding.sample_size, 'project'))} · {plain(plural(len(finding.affected_editors), 'Editor'))} · {text['uncertainty']}"
                         + (f" · {len(finding.contradicting_evidence)} contradicting evidence block(s)" if finding.contradicting_evidence else "")),
            "why_it_matters": text["management_significance"],
            "next_step": text["suggested_investigation"],
            "question": text["investigation_question"],
            "parameter_status": "approved" if all(use.status == "approved" for use in finding.parameters) else "proposed_not_approved",
        })
    return brief
