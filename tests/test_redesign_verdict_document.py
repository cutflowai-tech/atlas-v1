"""Redesign T2.1: the verdict document is part of every contract 1.5 snapshot, schema-valid, and optional for publication."""

import json
import unittest

from redesign_site import document, site

from atlas_commander import optional_artifacts, site_layout
from atlas_commander.contracts import schema_errors
from atlas_commander.verdict.engine import SCHEMA
from atlas_commander.verdict.site import VERDICTS_JSON


class VerdictDocumentTests(unittest.TestCase):
    def test_the_snapshot_contains_a_schema_valid_verdict_document(self):
        verdicts = document(VERDICTS_JSON)
        self.assertEqual(schema_errors(verdicts, SCHEMA), [])
        dashboard = document(site_layout.DASHBOARD_JSON)
        self.assertEqual(verdicts["source"]["retrieved_at"], dashboard["source"]["retrieved_at"])
        self.assertEqual(verdicts["executable_contract_version"], dashboard["source"]["executable_contract_version"])

    def test_it_is_an_optional_artifact_validated_by_its_own_checker(self):
        self.assertIn(VERDICTS_JSON, site_layout.optional_files("1.5.0"))
        self.assertEqual(site_layout.optional_files("1.4.0"), [])
        path = site() / VERDICTS_JSON
        retrieved = document(site_layout.DASHBOARD_JSON)["source"]["retrieved_at"]
        self.assertEqual(optional_artifacts.problems(VERDICTS_JSON, path, "1.5.0", retrieved), [])
        self.assertTrue(optional_artifacts.problems(VERDICTS_JSON, path, "1.5.0", "2020-01-01T00:00:00Z"))

    def test_a_malformed_document_is_rejected(self):
        broken = dict(document(VERDICTS_JSON), editors=[{"editor_id": "x"}])
        self.assertTrue(schema_errors(broken, SCHEMA))
        self.assertTrue(schema_errors(json.loads(json.dumps(dict(document(VERDICTS_JSON), document_version="0.9"))), SCHEMA))


if __name__ == "__main__":
    unittest.main()
