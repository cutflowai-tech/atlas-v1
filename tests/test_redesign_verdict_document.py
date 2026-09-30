"""Redesign T2.1: the verdict document is part of every contract 1.5 snapshot, schema-valid, and optional for publication."""

import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from redesign_site import document, site

from atlas_commander import optional_artifacts, profile_cli, site_layout
from atlas_commander.contracts import schema_errors
from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.runtime import load_contract_version
from atlas_commander.verdict import site as verdict_site
from atlas_commander.verdict.config import load_config
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

    def test_the_publication_gate_turns_the_document_off_without_breaking_the_build(self):
        contract = load_contract_version("1.5.0")
        out = Path(tempfile.mkdtemp(prefix="atlas-verdict-off-"))
        try:
            off = dataclasses.replace(load_config(), include_in_site_build=False)
            with mock.patch.object(verdict_site, "load_config", return_value=off):
                doc = profile_cli.build_all(profile_cli.reconstruct_extract(showcase_extract(), contract), contract, out, GENERATED_AT)
            self.assertFalse((out / VERDICTS_JSON).exists())
            editors = [s["editor_id"] for s in doc["editors"]]
            self.assertEqual([n for n in site_layout.required_files(editors, "1.5.0") if not (out / n).is_file()], [])
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
