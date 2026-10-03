"""analyst-v3 / update-v3: the prompts state the exact wording the Phase 15 guardrails check.

In the first live Stage 1 runs, every first answer was refused, mostly for wording the prompt never told the model about. The exact
live refusals are listed below:

- UNSUPPORTED_METRIC: 'historical rate', 'recorded rate', 'deadline-miss rate'.
- UNKNOWN_PERSON: 'editor-specific', 'editor-level'.
- UNSUPPORTED_NUMBER: 'two'.
- UNKNOWN_ENTITY: 'Compare' at the start of an investigation.
- CONFIDENCE_EXCEEDED: 'confirm'.
- HR_JUDGMENT: 'effort'.
- CAUSAL_OVERCLAIM: unhedged causal wording.
- WRONG_EVIDENCE_ROLE: contradicting records cited as support.

These tests pin both sides with the validator **unchanged**: each live refusal is still refused, and each safe wording the v3
prompt recommends instead is accepted. They also check that the prompt names every term the validator's own lists use, so the
two cannot drift apart silently.
"""

from __future__ import annotations

import copy
import unittest

from test_reasoning_guardrails import Fixture, showcase_case

from atlas_reasoning import analyst, guardrails, updater
from atlas_reasoning.guardrails import ValidationCode

SECTION = "## Wording Atlas checks automatically"

# (field, text the live model wrote or the minimal sentence carrying its refused term, the code it was refused with)
LIVE_REFUSALS = (
    ("observation", "The historical rate of late projects is higher than the baseline.", ValidationCode.UNSUPPORTED_METRIC),
    ("supporting_evidence", "The recorded rate of late projects is above the baseline.", ValidationCode.UNSUPPORTED_METRIC),
    ("title", "Deadline-miss rate above the baseline for editor-label-12", ValidationCode.UNSUPPORTED_METRIC),
    ("reasoning_summary", "The late pattern looks editor-specific.", ValidationCode.UNKNOWN_PERSON),
    ("management_significance", "This is an editor-level pattern in the late projects.", ValidationCode.UNKNOWN_PERSON),
    # Live: "two", where the case carried no 2. The showcase case does carry 2, so a number word it does not carry stands in.
    ("reasoning_summary", "The late pattern spans seventeen windows.", ValidationCode.UNSUPPORTED_NUMBER),
    ("suggested_investigations", "Compare projects across the current and previous windows.", ValidationCode.UNKNOWN_ENTITY),
    ("suggested_investigations", "Management could confirm whether the briefs changed.", ValidationCode.CONFIDENCE_EXCEEDED),
    ("interpretation", "The late projects reflect the effort put into each brief.", ValidationCode.HR_JUDGMENT),
    ("interpretation", "The late projects are due to changes in the briefs.", ValidationCode.CAUSAL_OVERCLAIM),
    ("observation", "The late projects may be due to changes in the briefs.", ValidationCode.CAUSAL_OVERCLAIM),   # factual: never causal
)

# The wording analyst-v3 recommends for the same content: every one passes the same, unchanged validator.
SAFE_WORDING = (
    ("observation", "The late rate in the current window is higher than the baseline late rate."),
    ("supporting_evidence", "The late projects in the current window form the pattern."),
    ("title", "Late rate above the baseline for editor-label-12"),
    ("reasoning_summary", "The late pattern appears for each Editor in scope."),
    ("management_significance", "The pattern concerns the late projects per Editor in scope."),
    ("reasoning_summary", "The late pattern appears in the current window and the previous window."),
    ("suggested_investigations", "Management could compare the late projects across the current and previous windows."),
    ("suggested_investigations", "Management could check whether the briefs changed."),
    ("interpretation", "The late projects may be associated with changes in the briefs."),
    ("interpretation", "This may be linked to changes in the briefs."),
    ("observation", "The late projects coincide with changes in the briefs."),
)


def set_text(fixture: Fixture, field: str, text: str) -> dict:
    answer = copy.deepcopy(fixture.answer)
    if field in ("supporting_evidence", "suggested_investigations"):
        key = "statement" if field == "supporting_evidence" else "text"
        answer[field][0][key] = text
        return fixture.candidate(answer)
    return fixture.with_text(field, text)


class LiveRefusalTests(unittest.TestCase):
    def setUp(self):
        self.f = Fixture(showcase_case())
        self.assertEqual(self.f.codes(), set())             # the grounded baseline answer passes

    def codes(self, field: str, text: str) -> set[str]:
        return self.f.codes(set_text(self.f, field, text))

    def test_each_live_refusal_is_still_refused(self):
        for field, text, code in LIVE_REFUSALS:
            with self.subTest(field=field, text=text):
                self.assertIn(code.value, self.codes(field, text))

    def test_the_wording_v3_recommends_is_accepted(self):
        for field, text in SAFE_WORDING:
            with self.subTest(field=field, text=text):
                self.assertEqual(self.codes(field, text), set())

    def test_contradicting_records_are_never_support(self):
        _, support, counter = guardrails._role_sets(self.f.case)
        self.assertTrue(support and counter)
        answer = copy.deepcopy(self.f.answer)
        answer["supporting_evidence"][0]["evidence_refs"] = [min(support), min(counter)]
        self.assertIn(ValidationCode.WRONG_EVIDENCE_ROLE.value, self.f.codes(self.f.candidate(answer)))
        answer["supporting_evidence"][0]["evidence_refs"] = [min(support)]           # what the v3 role rule asks for
        self.assertNotIn(ValidationCode.WRONG_EVIDENCE_ROLE.value, self.f.codes(self.f.candidate(answer)))


class PromptTests(unittest.TestCase):
    def setUp(self):
        # Whitespace-normalized: the prompts wrap lines.
        self.prompts = {version: " ".join(analyst.prompt_text(version).split())
                        for version in (analyst.ANALYST_PROMPT_VERSION, updater.UPDATE_PROMPT_VERSION)}

    def test_the_current_prompts_carry_the_wording_section(self):
        self.assertEqual((analyst.ANALYST_PROMPT_VERSION, updater.UPDATE_PROMPT_VERSION), ("analyst-v3", "update-v3"))
        sections = {version: text[text.index(SECTION): text.index("Atlas sets the case identity")] for version, text in self.prompts.items()}
        self.assertEqual(len(set(sections.values())), 1)     # one shared section, identical in both prompts

    def test_every_recommended_wording_is_in_the_prompt(self):
        for text in self.prompts.values():
            for phrase in ("Management could", "check whether", "for each Editor", "per Editor", "the baseline late rate",
                           "is associated with", "coincides with", "may", "might", "could", "possibly"):
                self.assertIn(phrase, text)

    def test_every_live_refused_term_is_named_in_the_prompt(self):
        for text in self.prompts.values():
            for term in ("historical rate", "recorded rate", "deadline-miss rate", "editor-level", "editor-specific", '"two"',
                         "Compare projects", "confirm", "effort", "due to"):
                self.assertIn(term, text)

    def test_the_prompt_names_the_validator_vocabulary(self):
        """Drift guard: the allowed rates and representative terms of each validator list are named in the prompt."""
        for text in self.prompts.values():
            lowered = text.lower()
            for rate in guardrails._ALLOWED_RATES:
                if rate in ("on time", "ontime"):
                    continue          # spelling variants of "on-time", which the prompt names
                self.assertIn(rate, lowered)
            for term in ("score", "index", "rating", "ranking", "kpi", "productivity", "efficiency", "percentile", "grade", "composite",
                         "utilization", "ratio"):
                self.assertRegex(lowered, rf"\b{term}\b")
                self.assertRegex(term, guardrails._METRIC_NOUNS)
            for term in ("caused", "because of", "due to", "led to", "driven by", "responsible for", "attributable to", "stems from"):
                self.assertIn(term, lowered)
                self.assertTrue(guardrails._CAUSAL.search(term))
            for term in ("effort", "motivation", "health", "underperforming", "salary", "promotion", "burnout", "careless"):
                self.assertIn(term, lowered)
                self.assertTrue(guardrails._HR.search(term))
            for term in ("proves", "confirm", "definitely", "certainly", "obviously", "guaranteed"):
                self.assertIn(term, lowered)
                self.assertTrue(guardrails._CERTAINTY.search(term))
            for term in ("clearly", "evident", "strong evidence", "strong pattern"):
                self.assertIn(term, lowered)
                self.assertTrue(guardrails._HIGH_CONFIDENCE.search(term))

    def test_the_validator_is_unchanged(self):
        self.assertEqual(guardrails.VALIDATOR_VERSION, VALIDATOR_VERSION_BEFORE_V3)


VALIDATOR_VERSION_BEFORE_V3 = guardrails.VALIDATOR_VERSION


if __name__ == "__main__":
    unittest.main()
