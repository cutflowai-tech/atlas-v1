"""Redesign T4.1: every message key the verdict engine can write has an English and an Arabic template, and renders in both.

The test fails when the engine emits a key (or a parameter) the registry ``atlas_commander.verdict.messages`` does not list, when a
registered key has no template in either language, when a template uses a parameter its key does not carry, or when a registered key
can no longer be produced (a stale template).
"""

import ast
import copy
import dataclasses
import itertools
import json
import re
import string
import unittest
from pathlib import Path

from verdict_fixture import fixture, verdicts

from atlas_commander.i18n import AR, EN, catalog
from atlas_commander.verdict import messages, sentences
from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.decisions import low_activity_decision
from atlas_commander.verdict.engine import build_verdicts
from atlas_commander.verdict.inputs import Overdue, msg, normalize
from atlas_commander.verdict.reasoning import RUNWAY_EXPLAINS, RUNWAY_NOT_EXPLAINING, RunwayResult
from atlas_commander.verdict.team import team_verdict
from atlas_commander.web.verdict_ui import message

CONFIG = load_config()
VERDICT_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "atlas_commander" / "verdict"
AR_LETTER = re.compile(r"[؀-ۿ]")


def _msgs(node):
    """Every Msg inside a verdict document (or part of one)."""
    if isinstance(node, dict):
        if isinstance(node.get("key"), str) and node["key"].startswith("verdict.") and set(node) == {"key", "params"}:
            yield node
        for value in node.values():
            yield from _msgs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _msgs(value)


def _documents():
    """The fixture and variants that reach the engine's other branches."""
    data = fixture()
    yield verdicts()
    yield build_verdicts(data["dashboard"], None, data["dashboard"]["generated_at"])
    approved = copy.deepcopy(data)
    for e in approved["dashboard"]["editors"]:
        e["interpretation"]["components"]["quality"].update(rule_status="approved", state="positive")
    yield build_verdicts(approved["dashboard"], approved["intelligence"], approved["dashboard"]["generated_at"])   # 0% for everyone: review
    measured = copy.deepcopy(approved)
    for e, state in zip(measured["dashboard"]["editors"], itertools.cycle(messages.QUALITY_STATES), strict=False):
        quality = e["interpretation"]["components"]["quality"]
        quality["state"] = state
        if quality["facts"]["negative_rate"] is not None:
            quality["facts"]["negative_rate"] = 0.1                                   # a Quality rule that measures: its states show
    yield build_verdicts(measured["dashboard"], measured["intelligence"], measured["dashboard"]["generated_at"])
    mirrored = copy.deepcopy(data)
    speed = next(f for f in mirrored["intelligence"]["findings"] if f["finding_id"] == "change.editor:refaat-speed")
    speed["statements"][0]["params"]["team_pct_change"] = 20.0                        # Refaat's +26.3% is now the team's change too
    yield build_verdicts(mirrored["dashboard"], mirrored["intelligence"], mirrored["dashboard"]["generated_at"])
    bare = copy.deepcopy(data)
    for f in bare["intelligence"]["findings"]:
        f.pop("supporting_evidence", None)
    yield build_verdicts(bare["dashboard"], bare["intelligence"], bare["dashboard"]["generated_at"])


def _sentence_sweep():
    """Headlines and reasons for every tier under every combination of the facts that choose them."""
    data = fixture()
    editors = normalize(data["dashboard"], data["intelligence"])[0]
    base = next(e for e in editors if e.display_name == "Refaat")
    label = msg("verdict.speed.label", labels=["Simple Short"], editor_hours=41.6, peer_hours=29.1, n=11)
    runways = [None, RunwayResult(RUNWAY_EXPLAINS, msg("verdict.reason.runway_explains", short_share_pct=85.0, team_short_share_pct=77.4, late=20, short=17)),
               RunwayResult(RUNWAY_NOT_EXPLAINING, msg("verdict.reason.runway_not_explaining", late_pct=85.7, short_runway_late_pct=73.2))]
    mirrors = [None, msg("verdict.reason.mirrors_team_late_rate", before_pct=69.2, now_pct=53.8, team_before_pct=75.6, team_now_pct=59.0),
               msg("verdict.reason.mirrors_team_speed", change_pct=26.3, team_change_pct=20.0)]
    lates = [(None, 0, None), (0.857, 14, 12), (0.30, 10, 3), (0.589, 10, 6), (0.62, 10, 6)]
    speeds = [(None, False), (43.0, True), (-23.0, True), (2.0, True), (27.0, True)]
    for tier, runway, mirror, (rate, n, late), (speed, classified), own, completed, active, overdue, mirrored in itertools.product(
            messages.TIERS, runways, mirrors, lates, speeds, (None, 26.3, -12.0), (0, 2, 14, 24), (0, 1), (0, 2), (False, True)):
        editor = dataclasses.replace(base, overdue=tuple(Overdue(str(i), "Revisions", None, 3.0) for i in range(overdue)))
        metrics = {"late_rate": rate, "team_late_rate": 0.589, "late_count": late, "deadline_classifiable": n, "speed_delta_pct": speed,
                   "speed_classified": classified, "speed_label": label if speed is not None else None, "own_speed_delta_pct": own,
                   "completed": completed, "active": active, "lifetime_completed": 60}
        context = sentences.Context(editor=editor, metrics=metrics, tier=tier, ranked=completed >= 5, median_completed=15.0 if completed >= 5 else None,
                                    highest_completed=24, runway=runway, mirror=mirror, own_change_mirrored=mirrored)
        yield sentences.headline(context, CONFIG)
        yield from sentences.reasons(context, CONFIG)


def _team_sweep():
    data = fixture()
    team = normalize(data["dashboard"], data["intelligence"])[1]
    for late, previous, overdue, share, intelligence in itertools.product((0, 20, 60, 90), (0, 55, 90, None), (0, 3, 6), (0.30, 0.77, None), (True, False)):
        split = None if share is None else dict(team.runway, share_of_late_with_short_runway=share)
        variant = dataclasses.replace(team, late=late, classifiable=100 if late else 0, previous_late=previous or 0, previous_classifiable=0 if previous is None else 100,
                                      overdue=tuple(("x", Overdue(str(i), "Revisions", None, 1.0)) for i in range(overdue)), runway=split, intelligence_available=intelligence)
        yield from _msgs(team_verdict(variant, CONFIG))


def _decision_sweep():
    data = fixture()
    editors = normalize(data["dashboard"], data["intelligence"])[0]
    idle = [e for e in editors if e.display_name in ("Samra", "Ahmed")]              # only zero-activity Editors to ask
    yield from _msgs(low_activity_decision(idle))


def emitted():
    found = [m for document in _documents() for m in _msgs(document)]
    return found + list(_sentence_sweep()) + list(_team_sweep()) + list(_decision_sweep())


def _fields(template: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(template) if field}


class MessageRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.messages = emitted()
        cls.keys = {m["key"] for m in cls.messages}

    def test_every_emitted_key_and_parameter_is_registered(self):
        self.assertEqual(self.keys - set(messages.KEYS), set())
        for m in self.messages:
            self.assertLessEqual(set(m["params"]), set(messages.KEYS[m["key"]]), m)
            if m["key"] in messages.PLURAL:
                self.assertIsInstance(m["params"].get("count"), int, m)

    def test_every_registered_key_can_be_produced(self):
        self.assertEqual(set(messages.KEYS) - self.keys, set(), "a template for a key the engine never writes")

    def test_every_literal_key_in_the_engine_is_registered(self):
        for path in VERDICT_PACKAGE.glob("*.py"):
            if path.name == "messages.py":
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r"verdict\.[a-z0-9_.]+", node.value):
                    self.assertTrue(any(key == node.value or key.startswith(node.value) for key in messages.KEYS), f"{path.name}: {node.value}")


class MessageTemplateTests(unittest.TestCase):
    def test_every_key_has_both_templates_with_only_its_parameters(self):
        entries = catalog()
        for key, params in messages.KEYS.items():
            entry = entries.get(key)
            self.assertIsNotNone(entry, f"no catalogue entry for {key}")
            allowed = (set(params) - {"count"}) | ({"n"} if key in messages.PLURAL else set())
            for locale in ("en", "ar"):
                texts = entry[locale]
                if key in messages.PLURAL:
                    self.assertIsInstance(texts, dict, (key, locale))
                    self.assertLessEqual({"one", "other"}, set(texts), (key, locale))
                    if locale == "ar":
                        self.assertLessEqual({"zero", "one", "two", "few", "many", "other"}, set(texts), key)
                    texts = list(texts.values())
                else:
                    self.assertIsInstance(texts, str, (key, locale))
                    texts = [texts]
                for text in texts:
                    self.assertTrue(text.strip(), (key, locale))
                    self.assertLessEqual(_fields(text), allowed, (key, locale, text))
            if key not in messages.PLURAL:
                self.assertEqual(_fields(entry["en"]), _fields(entry["ar"]), key)       # both languages say the same facts
        self.assertEqual({k for k in entries if k.startswith("verdict.")} - set(messages.KEYS), set())

    def test_every_emitted_message_renders_in_both_languages(self):
        for m in {json.dumps(m, sort_keys=True): m for m in emitted()}.values():
            english, arabic = str(message(m, EN)), str(message(m, AR))
            for text in (english, arabic):
                self.assertNotRegex(text, r"\{[a-z_]+\}", m)
                self.assertTrue(text.strip(), m)
            template = catalog()[m["key"]]["ar"]
            if AR_LETTER.search(json.dumps(template, ensure_ascii=False)):
                self.assertRegex(arabic, AR_LETTER, m)                                    # the Arabic page never shows the English text

    def test_rendering_follows_the_units(self):
        refaat = next(e for e in verdicts()["editors"] if e["display_name"] == "Refaat")
        self.assertEqual(str(message(refaat["headline"], EN)),
                         'The weakest this month: late on <bdi dir="ltr">86%</bdi> of projects, <bdi dir="ltr">43%</bdi> slower than peers and '
                         '<bdi dir="ltr">26%</bdi> slower than their own earlier work. Scheduling does not explain it.')
        self.assertIn('<bdi dir="ltr">86%</bdi>', str(message(refaat["headline"], AR.isolating())))
        overdue = {"key": "verdict.reason.overdue_open", "params": {"count": 1}}
        self.assertEqual(str(message(overdue, EN)), "One open project is past its deadline.")
        self.assertEqual(str(message(dict(overdue, params={"count": 2}), AR)), "مشروعان مفتوحان تجاوزا موعدهما.")
        self.assertIn('<data value="5">5</data> مشاريع', str(message(dict(overdue, params={"count": 5}), AR)))
        speed = {"key": "verdict.reason.mirrors_team_speed", "params": {"change_pct": -12.4, "team_change_pct": -4.0}}
        self.assertIn("−12%", str(message(speed, EN)))                                            # a signed change keeps its sign
        rule = {"key": "verdict.decision.approve_rule", "params": {"dimension": "quality"}}
        self.assertEqual(str(message(rule, AR)), "اعتمد قاعدة الجودة. Atlas لا يرى الجودة حاليًا.")
        with self.assertRaises(KeyError):
            message({"key": "verdict.reason.unknown", "params": {}}, EN)
        with self.assertRaises(KeyError):
            message({"key": "verdict.reason.in_progress", "params": {"active": 1, "extra": 2}}, EN)


if __name__ == "__main__":
    unittest.main()
