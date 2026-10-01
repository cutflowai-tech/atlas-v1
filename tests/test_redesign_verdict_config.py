"""Redesign T2.2: one configuration holds every verdict threshold and weight (D54); the engine has no other magic number."""

import ast
import copy
import json
import re
import unittest
from pathlib import Path

from atlas_commander.investigation.policy import CONFIG_PATH as INTELLIGENCE_CONFIG_PATH
from atlas_commander.verdict import config as verdict_config
from atlas_commander.verdict.config import CONFIG_PATH, ConfigError, config_from, load_config

ROOT = CONFIG_PATH.parents[1]
DOCUMENT = json.loads(CONFIG_PATH.read_text())
INTELLIGENCE = json.loads(INTELLIGENCE_CONFIG_PATH.read_text())
ALLOWED_LITERALS = {0, 1, 2, 12, 100, 3600}   # identities, halves (a median), the schema's 12-digit decision ID, percent and hour conversions; every threshold is configured


class ConfigTests(unittest.TestCase):
    def test_every_parameter_is_approved_numeric_and_explained(self):
        config = load_config()
        self.assertEqual(config.decision_id, "D54")
        self.assertEqual(set(config.values), set(DOCUMENT["parameters"]))
        for name, parameter in DOCUMENT["parameters"].items():
            self.assertTrue(parameter["meaning"].strip(), name)
            self.assertIsInstance(config[name], (int, float), name)

    def test_shared_values_are_read_from_the_intelligence_configuration(self):
        config = load_config()
        self.assertEqual(config["reasoning.material_rate_difference"], INTELLIGENCE["parameters"]["evidence.material_rate_difference"]["value"])
        self.assertEqual(config["reasoning.material_duration_pct"], INTELLIGENCE["parameters"]["evidence.material_duration_pct"]["value"])

    def test_decision_log_and_configuration_agree(self):
        log = (ROOT / "docs" / "DECISIONS.md").read_text()
        section = log.split("## D54")[1].split("\n## ")[0]
        for name, parameter in DOCUMENT["parameters"].items():
            if "from_config" in parameter:
                self.assertIn(parameter["from_config"].split(":")[1], section, name)
            else:
                self.assertIn(f"`{name}` = {parameter['value']}", section, name)
        self.assertEqual(len(re.findall(r"^\| .* \| .* \|$", section, re.MULTILINE)) - 1, len(DOCUMENT["parameters"]))   # minus the header

    def test_an_unapproved_or_unexplained_value_is_refused(self):
        for mutate in (lambda d: d["parameters"]["tier.watch_speed_pct"].update(decision_id="D99"),
                       lambda d: d["parameters"]["tier.watch_speed_pct"].update(meaning=""),
                       lambda d: d["parameters"]["tier.watch_speed_pct"].update(value="25"),
                       lambda d: d["governance"].update(decision_id=None),
                       lambda d: d["parameters"]["reasoning.material_duration_pct"].update(decision_id="D54")):
            document = copy.deepcopy(DOCUMENT)
            mutate(document)
            with self.assertRaises(ConfigError):
                config_from(document, INTELLIGENCE)

    def test_the_engine_contains_no_threshold_literal(self):
        package = Path(verdict_config.__file__).parent
        for path in sorted(package.glob("*.py")):
            if path.name == "config.py":
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                    self.assertIn(node.value, ALLOWED_LITERALS, f"{path.name}:{node.lineno} literal {node.value!r}")


if __name__ == "__main__":
    unittest.main()
