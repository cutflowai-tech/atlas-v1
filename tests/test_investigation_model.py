"""Intelligence V2 domain model, parameter governance (D25), confidence, narrative and AI-guard tests."""

import copy
import json
import re
import unittest
from typing import ClassVar

import investigation_factory as f

from atlas_commander.investigation import narrative
from atlas_commander.investigation.ai_guard import accept_rewrite, rewrite_problems
from atlas_commander.investigation.catalog import DETECTORS
from atlas_commander.investigation.confidence import MODERATE, STRONG, WEAK, assess
from atlas_commander.investigation.models import (
    ADVERSE,
    FACT,
    HYPOTHESIS,
    INTERPRETATION,
    METRIC,
    SYSTEM_PATTERN,
    Evidence,
    EvidenceRecord,
    Finding,
    Scope,
    Statement,
    finding_errors,
)
from atlas_commander.investigation.policy import (
    APPROVED_ONLY,
    CONFIG_PATH,
    PROPOSED_NOT_APPROVED,
    REVIEW,
    IntelligencePolicy,
    ParameterUse,
    RuleNotApproved,
    config_errors,
    load_capability_map,
)


def record(item="1", events=("e1",), times=("2026-09-01T00:00:00Z",)):
    return EvidenceRecord(item, f"cycle:{item}", events, times, {"value": 1}, "editor-label-6", "4")


def finding(**changes):
    values = {"finding_type": "concentration.negative", "detector_version": "v", "category": SYSTEM_PATTERN, "direction": ADVERSE,
              "scope": Scope("video_type", cohort_key="4"), "statements": [Statement(METRIC, "m", {}), Statement(INTERPRETATION, "i", {})],
              "supporting_evidence": [Evidence("supporting", "c", "calc", {"n": 1}, [record()])], "parameters": [], "time_window": {"window": "current"},
              "limitations": ["x"], "significance": Statement(INTERPRETATION, "s", {}), "investigations": [Statement(HYPOTHESIS, "h", {})], "key": {"k": 1}}
    values.update(changes)
    return Finding(**values)


class FindingModelTests(unittest.TestCase):
    def test_valid_finding_has_no_errors_and_highest_level(self):
        item = finding()
        self.assertEqual(finding_errors(item), [])
        self.assertEqual(item.evidence_level, METRIC)
        self.assertEqual(item.statement_levels, [METRIC, INTERPRETATION])

    def test_interpretation_without_observation_is_rejected(self):
        self.assertIn("an interpretation or hypothesis needs a fact, metric, pattern or association in the same finding",
                      finding_errors(finding(statements=[Statement(INTERPRETATION, "i", {}), Statement(HYPOTHESIS, "h", {})])))

    def test_evidence_without_records_or_event_ids_is_rejected(self):
        self.assertTrue(finding_errors(finding(supporting_evidence=[Evidence("supporting", "c", "calc", {}, [])])))
        errors = finding_errors(finding(supporting_evidence=[Evidence("supporting", "c", "calc", {}, [record(events=())])]))
        self.assertTrue(any("no Monday event IDs" in error for error in errors))

    def test_limitations_are_mandatory(self):
        self.assertIn("a finding must declare its limitations", finding_errors(finding(limitations=[])))

    def test_editor_finding_must_name_editor_and_never_interpret_revisions(self):
        self.assertIn("an Editor finding must name the Editor", finding_errors(finding(scope=Scope("editor"))))
        errors = finding_errors(finding(scope=Scope("editor", editor_id="e"), statements=[Statement(FACT, "f", {}), Statement(INTERPRETATION, "revision_fault", {})]))
        self.assertTrue(any("D31" in error for error in errors))

    def test_finding_id_is_deterministic_and_key_sensitive(self):
        self.assertEqual(finding().finding_id, finding().finding_id)
        self.assertNotEqual(finding().finding_id, finding(key={"k": 2}).finding_id)
        self.assertRegex(finding().finding_id, r"^concentration\.negative:[0-9a-f]{16}$")

    def test_affected_sets_come_from_records(self):
        item = finding(supporting_evidence=[Evidence("supporting", "c", "calc", {}, [record("1"), record("2")])])
        self.assertEqual(item.affected_projects, ["1", "2"])
        self.assertEqual(item.sample_size, 2)
        self.assertEqual(item.affected_video_types, ["4"])

    def test_unknown_level_scope_is_refused(self):
        with self.assertRaises(ValueError):
            Statement("guess", "x", {})
        with self.assertRaises(ValueError):
            Scope("client")


class PolicyTests(unittest.TestCase):
    def test_shipped_configuration_is_valid(self):
        self.assertEqual(config_errors(json.loads(CONFIG_PATH.read_text()), f.CONTRACT), [])

    def test_reused_values_come_from_the_contract_and_its_approval(self):
        policy = IntelligencePolicy.load(f.CONTRACT)
        speed = policy.use("speed.minimum_editor_projects")
        self.assertEqual((speed.value, speed.status, speed.decision_id), (5, "approved", "D52"))
        self.assertEqual(policy.value("deadline.minimum_comparator_projects"), 60)
        contract = copy.deepcopy(f.CONTRACT)
        contract["speed_benchmark"]["minimum_editor_sample_size_status"] = "rule_not_approved"
        contract["speed_benchmark"]["minimum_editor_sample_size"] = None
        self.assertIsNone(IntelligencePolicy.load(contract).use("speed.minimum_editor_projects"))

    def test_unapproved_values_are_unavailable_in_approved_only(self):
        policy = IntelligencePolicy.load(f.CONTRACT, APPROVED_ONLY, f.pre_d53())
        self.assertIsNone(policy.use("runway.short_rule"))
        with self.assertRaises(RuleNotApproved) as caught:
            policy.require("runway.short_rule", "speed.minimum_editor_projects", "evidence.material_rate_difference")
        self.assertEqual(caught.exception.names, ["evidence.material_rate_difference", "runway.short_rule"])
        self.assertTrue(policy.publishable)

    def test_review_mode_uses_proposals_marked_not_approved(self):
        policy = IntelligencePolicy.load(f.CONTRACT, REVIEW, f.pre_d53())
        use = policy.use("evidence.minimum_group_projects")
        self.assertEqual((use.value, use.status, use.decision_id), (10, PROPOSED_NOT_APPROVED, None))
        self.assertFalse(policy.publishable)

    def test_config_errors_enforce_d25(self):
        data = json.loads(CONFIG_PATH.read_text())
        bad = f.pre_d53()
        bad["parameters"]["runway.short_rule"]["value"] = "x"
        self.assertTrue(any("not approved (D25)" in error for error in config_errors(bad)))
        bad = copy.deepcopy(data)
        bad["parameters"]["evidence.minimum_group_projects"]["decision_id"] = None
        self.assertTrue(any("without a decision_id" in error for error in config_errors(bad)))
        bad = copy.deepcopy(data)
        bad["parameters"]["evidence.minimum_group_projects"]["decision_id"] = "D99"
        self.assertTrue(any("not an approved Intelligence V2 decision" in error for error in config_errors(bad)))
        bad = copy.deepcopy(data)
        bad["parameters"]["speed.minimum_editor_projects"]["value"] = 3
        self.assertTrue(any("must come from the contract" in error for error in config_errors(bad)))
        bad = copy.deepcopy(data)
        bad["publication"]["mode"] = "review"
        self.assertTrue(any("never published" in error for error in config_errors(bad)))
        with self.assertRaises(ValueError):
            IntelligencePolicy.load(f.CONTRACT, "guess")

    def test_every_parameter_named_by_a_detector_exists(self):
        names = set(json.loads(CONFIG_PATH.read_text())["parameters"])
        for detector in DETECTORS:
            self.assertLessEqual(set(detector.parameters), names, detector.detector_id)

    def test_no_detector_depends_on_unavailable_or_unsafe_data(self):
        signals = load_capability_map()["signals"]
        for detector in DETECTORS:
            for signal in detector.required_signals:
                self.assertIn(signal, signals, f"{detector.detector_id} names an unmapped signal {signal}")
                self.assertNotIn(signals[signal]["class"], ("unavailable", "unsafe_to_infer"), f"{detector.detector_id} needs {signal}")

    def test_every_detector_has_a_complete_catalog_entry(self):
        ids = [detector.detector_id for detector in DETECTORS]
        self.assertEqual(len(ids), len(set(ids)))
        for detector in DETECTORS:
            entry = detector.catalog_entry()
            for key in ("purpose", "minimum_sample", "output", "confidence_rules", "version", "task"):
                self.assertTrue(entry[key], f"{detector.detector_id}.{key}")
            self.assertTrue(entry["limitations"], detector.detector_id)


class D53ApprovalTests(unittest.TestCase):
    """D53 (2026-09-30): the management decision, the configuration and the policy agree on every approved value (D25)."""

    APPROVED: ClassVar[dict] = {"evidence.minimum_group_projects": 10, "evidence.minimum_outcome_events": 5, "evidence.minimum_editors_for_breadth": 3,
                "evidence.minimum_projects_per_editor_for_breadth": 5, "evidence.breadth_share": "2/3", "concentration.minimum_share_ratio": 1.25,
                "concentration.minimum_share_difference": 0.10, "evidence.material_rate_difference": 0.15, "evidence.material_duration_pct": 25,
                "runway.short_rule": "runway_below_typical_execution", "workload.band_rule": "above_editor_own_median", "workload.high_percentile": 0.75,
                "risk.elapsed_percentile": 0.75, "patterns.maximum_combinations": 40, "confidence.sample_multiple": 2,
                "confidence.minimum_completeness": 0.9, "prioritization.top_findings": 5, "prioritization.duplicate_overlap": 0.8}

    def test_every_d53_value_is_approved_in_approved_only_mode(self):
        policy = IntelligencePolicy.load(f.CONTRACT, APPROVED_ONLY)
        for name, value in self.APPROVED.items():
            use = policy.use(name)
            self.assertIsNotNone(use, name)
            self.assertEqual((use.value, use.status, use.decision_id), (value, "approved", "D53"), name)

    def test_no_parameter_is_left_unapproved(self):
        policy = IntelligencePolicy.load(f.CONTRACT, APPROVED_ONLY)
        self.assertEqual([name for name, parameter in policy.parameters.items() if not parameter.approved], [])

    def test_decision_log_records_d53_as_approved(self):
        log = (CONFIG_PATH.parents[1] / "docs" / "DECISIONS.md").read_text()
        heading = next(line for line in log.splitlines() if line.startswith("##") and "D53" in line)
        self.assertIn("approved by Waset management", heading)
        self.assertNotIn("Proposed, not approved: D53", log)
        section = log[log.index(heading):]
        section = section[: section.index("\n## ", 1)]
        self.assertNotIn("Status: OPEN", section)
        for value in ("10 projects", "5 relevant outcome events", "3 affected Editors", "two thirds", "1.25", "10 percentage points", "15 percentage points",
                      "25%", "75th percentile", "40", "Top 5"):
            self.assertIn(value, section, value)

    def test_a_decision_the_log_does_not_approve_cannot_approve_a_parameter(self):
        data = f.config()
        data["parameters"]["runway.short_rule"]["decision_id"] = "D54"
        with self.assertRaises(ValueError):
            IntelligencePolicy.load(f.CONTRACT, APPROVED_ONLY, data)


class ConfidenceTests(unittest.TestCase):
    def setUp(self):
        self.review = IntelligencePolicy.load(f.CONTRACT, REVIEW)

    def test_levels_follow_the_published_rule(self):
        strong = assess(self.review, groups={"a": (40, 10)}, replication=[{"slice": "x", "holds": True}, {"slice": "y", "holds": True}],
                        completeness=(95, 100))
        self.assertEqual(strong["level"], STRONG)
        moderate = assess(self.review, groups={"a": (40, 10)}, replication=[{"slice": "x", "holds": True}], completeness=(95, 100))
        self.assertEqual(moderate["level"], MODERATE)
        low = assess(self.review, groups={"a": (12, 10)}, replication=[{"slice": "x", "holds": False}])
        self.assertEqual(low["level"], WEAK)

    def test_contradicting_evidence_prevents_strong(self):
        result = assess(self.review, groups={"a": (40, 10)}, replication=[{"slice": "x", "holds": True}] * 2, contradictions=1, completeness=(100, 100))
        self.assertEqual(result["level"], MODERATE)
        self.assertIn("contradicting_evidence:limits", result["why"])

    def test_incomplete_data_prevents_strong(self):
        result = assess(self.review, groups={"a": (40, 10)}, replication=[{"slice": "x", "holds": True}] * 2, completeness=(50, 100))
        self.assertEqual(result["level"], MODERATE)

    def test_unapproved_method_parameters_are_not_assessed_and_cap_below_strong(self):
        result = assess(IntelligencePolicy.load(f.CONTRACT, APPROVED_ONLY, f.pre_d53()), groups={"a": (400, 10)}, replication=[{"slice": "x", "holds": True}] * 3,
                        completeness=(100, 100))
        self.assertNotEqual(result["level"], STRONG)
        self.assertEqual(result["factors"][0]["assessment"], "not_assessed")
        self.assertEqual(result["method_status"], "proposed_not_approved")

    def test_every_level_explains_itself_without_percentages(self):
        result = assess(self.review, groups={"a": (12, 10)})
        self.assertTrue(result["factors"] and result["why"] and result["rule"])
        self.assertNotRegex(json.dumps(result), r"\d+\.\d+%")


class NarrativeTests(unittest.TestCase):
    def test_forbidden_language_never_appears_in_templates(self):
        with open(narrative.__file__, encoding="utf-8") as handle:
            source = handle.read()
        templates = source[source.index("T: dict[str, Callable"):source.index("LANGUAGE_RULES: dict")].lower()
        for pattern in (r"\blazy\b", r"careless", r"disciplin", r"terminat", r"salary", r"promot", r"punish", r"\bfault\b", r"\bcaused\b", r"\bcauses\b",
                        r"\bbecause of\b", r"\bwill be late\b(?! outcomes)", r"\bproves?\b"):
            self.assertIsNone(re.search(pattern, templates.replace("not a prediction that these projects will be late", "")), pattern)

    def test_formatting_helpers(self):
        plain = narrative.plain
        self.assertEqual(plain(narrative.pct(0.7206)), "72%")
        self.assertEqual(plain(narrative.pp(-0.15)), "15 percentage points")
        self.assertEqual(plain(narrative.hrs(31.62)), "31.6 h")
        self.assertEqual(plain(narrative.plural(1, "project")), "1 project")
        self.assertEqual(plain(narrative.plural(2, "project")), "2 projects")
        self.assertEqual(narrative.pct(0.7206), "\u206672%\u2069")                   # numbers are left-to-right isolated for the site
        self.assertEqual(narrative.mon("Simple Short"), "\u2068Simple Short\u2069")  # Monday values keep their own direction

    def test_missing_template_is_an_error_not_a_guess(self):
        with self.assertRaises(KeyError):
            narrative.render("not_a_code", {})


class AIGuardTests(unittest.TestCase):
    FINDING: ClassVar[dict] = {"confidence": {"level": "moderate"}, "affected_editors": ["editor-label-6"], "sample_size": 12,
               "statements": [{"params": {"late": 9, "projects": 12, "rate": 0.75}}], "text": {"summary": "9 of 12 projects were late (75%)."}}

    def test_faithful_rewrite_is_accepted(self):
        text, problems = accept_rewrite(self.FINDING, "Editor A: 9 of 12 projects late (75%).", {"editor-label-6": "Editor A"}, ["Editor A", "Editor B"])
        self.assertEqual(problems, [])
        self.assertTrue(text.startswith("Editor A"))

    def test_invented_number_is_rejected_and_deterministic_text_kept(self):
        text, problems = accept_rewrite(self.FINDING, "9 of 12 projects were late, 40% more than last year.", {}, [])
        self.assertTrue(any("numbers not in the finding" in problem for problem in problems))
        self.assertEqual(text, self.FINDING["text"]["summary"])

    def test_causal_blame_personality_and_hr_language_is_rejected(self):
        for rewrite in ("Workload caused the delays.", "This is the Editor's fault.", "A careless Editor.", "Consider disciplinary action.",
                        "The Editor should be promoted."):
            self.assertTrue(rewrite_problems(self.FINDING, rewrite, {}, []), rewrite)

    def test_overcertainty_and_other_people_are_rejected(self):
        self.assertTrue(rewrite_problems(self.FINDING, "This proves the delay.", {}, []))
        self.assertTrue(rewrite_problems(self.FINDING, "Editor B has the same issue.", {"editor-label-6": "Editor A"}, ["Editor A", "Editor B"]))


class CapabilityMapTests(unittest.TestCase):
    def test_every_signal_is_classified_with_limitations(self):
        data = load_capability_map()
        for name, signal in data["signals"].items():
            self.assertIn(signal["class"], data["classes"], name)
            self.assertIsInstance(signal["limitations"], list, name)
        for forbidden in ("revision_cause", "actor_person_for_shared_account", "working_hours_or_effort"):
            self.assertIn(data["signals"][forbidden]["class"], ("unavailable", "unsafe_to_infer"))

    def test_parameter_use_serialises(self):
        self.assertEqual(ParameterUse("a", 1, "approved", "D52").to_dict(), {"name": "a", "value": 1, "status": "approved", "decision_id": "D52"})


if __name__ == "__main__":
    unittest.main()

