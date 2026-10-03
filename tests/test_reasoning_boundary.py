"""Reasoning V3 Phase 01: the deterministic Atlas core is frozen and protected (``REV/01``).

- With Reasoning V3 disabled (the default) and enabled, the contract 1.5 site build is byte-identical to the build made before any
  Reasoning V3 code existed (``fixtures/golden/site-v1.5-showcase-sha256.json``, commit 001f6af); contracts 1.3 and 1.4 keep
  their own golden bytes.
- ``reasoning_input_boundary`` is the only path from Atlas into Reasoning V3; nothing upstream imports Reasoning V3.
- The boundary payload is deeply immutable and never aliases or mutates upstream documents (profiles, component states,
  Overall Status, Trend, Recent Change, Intelligence V2).
"""

import ast
import copy
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_profile import NOW, dataset

from atlas_commander import profile_cli
from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.pipeline import reconstruct_cycles
from atlas_commander.runtime import load_contract_version
from atlas_reasoning import reasoning_input_boundary as boundary
from atlas_reasoning import settings
from atlas_reasoning.frozen import thaw
from atlas_reasoning.reasoning_input_boundary import (
    BY_STATEMENT_LEVEL,
    FIELD_KINDS,
    ReasoningInputError,
    ReasoningInputUnavailable,
    build_reasoning_input,
    field_kinds,
    load_reasoning_input,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GOLDEN_15 = ROOT / "fixtures" / "golden" / "site-v1.5-showcase-sha256.json"
CONTRACT_15 = load_contract_version("1.5.0")
# Variables that change what a site build reads (photos); the golden build ran without them.
BUILD_ENV = ("ATLAS_EDITOR_PHOTOS", "ATLAS_DATA_DIR")


def _hashes(out: Path) -> dict[str, str]:
    return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob("*")) if p.is_file()}


def build_showcase(out: Path) -> dict:
    result = profile_cli.reconstruct_extract(showcase_extract(), CONTRACT_15)
    return profile_cli.build_all(result, CONTRACT_15, out, GENERATED_AT)


def _env(**extra: str) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in BUILD_ENV and key != settings.FLAG_ENV}
    env.update(extra)
    return env


class ShowcaseSite:
    """One showcase site built once per test class (the build takes a few seconds)."""

    out: Path

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="atlas-reasoning-boundary-"))
        with mock.patch.dict(os.environ, _env(), clear=True):
            build_showcase(cls.out)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def documents(self) -> tuple[dict, dict, list[dict]]:
        intelligence = json.loads((self.out / "intelligence-v2.json").read_text())
        publication = json.loads((self.out / "publication.json").read_text())
        profiles = [json.loads(p.read_text()) for p in sorted((self.out / "profiles").glob("*.json"))]
        return intelligence, publication, profiles


class FeatureFlagTests(unittest.TestCase):
    def test_default_is_off(self):
        self.assertFalse(settings.reasoning_enabled({}))
        with self.assertRaises(settings.ReasoningDisabled):
            settings.require_enabled({})

    def test_explicit_values(self):
        for raw in ("on", "1", "true", "YES", " On "):
            self.assertTrue(settings.reasoning_enabled({settings.FLAG_ENV: raw}), raw)
        for raw in ("off", "0", "false", "no", ""):
            self.assertFalse(settings.reasoning_enabled({settings.FLAG_ENV: raw}), raw)
        settings.require_enabled({settings.FLAG_ENV: "on"})

    def test_an_unclear_value_is_an_error_not_a_guess(self):
        with self.assertRaises(settings.ReasoningConfigError):
            settings.reasoning_enabled({settings.FLAG_ENV: "maybe"})


class GoldenSiteTests(unittest.TestCase):
    """V3 disabled (and enabled: Phase 01 adds no build hook) reproduces the pre-Reasoning-V3 site byte for byte."""

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="atlas-reasoning-golden-"))

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_contract_1_5_site_is_byte_identical_to_the_pre_reasoning_build(self):
        golden = json.loads(GOLDEN_15.read_text())
        self.assertEqual(golden["contract_version"], "1.5.0")
        for label, env in (("unset", _env()), ("off", _env(ATLAS_REASONING_V3="off")), ("on", _env(ATLAS_REASONING_V3="on"))):
            with self.subTest(flag=label), mock.patch.dict(os.environ, env, clear=True):
                out = self.out / label
                build_showcase(out)
                actual = _hashes(out)
                self.assertEqual(sorted(actual), sorted(golden["files"]), "the site has exactly the pre-Reasoning-V3 files")
                self.assertEqual(sorted(name for name in actual if actual[name] != golden["files"][name]), [], f"site output changed with the flag {label}")

    def test_historical_contracts_still_build_their_golden_bytes_with_the_flag_on(self):
        for version in ("1.3.0", "1.4.0"):
            with self.subTest(version=version), mock.patch.dict(os.environ, _env(ATLAS_REASONING_V3="on"), clear=True):
                contract = load_contract_version(version)
                activity, items_payload = dataset()
                out = self.out / version
                profile_cli.build_all(reconstruct_cycles(activity, contract, items_payload=items_payload, ingestion={"retrieved_at": NOW}), contract, out, NOW)
                golden = json.loads((ROOT / "fixtures" / "golden" / f"site-v{version[:3]}-sha256.json").read_text())
                self.assertEqual(_hashes(out), golden["files"])
                with self.assertRaises(ReasoningInputUnavailable):
                    load_reasoning_input(out)


class ImportDirectionTests(unittest.TestCase):
    """Exactly one approved input path: nothing upstream imports Reasoning V3, and inside Reasoning V3 only the boundary reads Atlas."""

    UPSTREAM = ("atlas_commander", "atlas_sync", "atlas_monday_probe")

    @staticmethod
    def _imports(path: Path) -> set[str]:
        names: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
        return names

    def test_no_upstream_module_imports_reasoning(self):
        offenders = [str(path.relative_to(ROOT)) for package in self.UPSTREAM for path in (SRC / package).rglob("*.py")
                     if "atlas_reasoning" in self._imports(path)]
        self.assertEqual(offenders, [])

    def test_only_the_boundary_reads_upstream_atlas(self):
        offenders = [str(path.relative_to(ROOT)) for path in (SRC / "atlas_reasoning").rglob("*.py")
                     if path.name != "reasoning_input_boundary.py" and self._imports(path) & set(self.UPSTREAM)]
        self.assertEqual(offenders, [])


class IntelligenceUnchangedTests(unittest.TestCase):
    def test_intelligence_v2_is_identical_before_and_after_importing_the_boundary(self):
        script = (
            "import hashlib, json, sys\n"
            "from atlas_commander.demo import GENERATED_AT, showcase_extract\n"
            "from atlas_commander.investigation.engine import build_intelligence\n"
            "from atlas_commander.profile_cli import reconstruct_extract\n"
            "from atlas_commander.runtime import load_contract_version\n"
            "c = load_contract_version('1.5.0')\n"
            "def digest():\n"
            "    doc = build_intelligence(reconstruct_extract(showcase_extract(), c), c, GENERATED_AT)\n"
            "    return doc, hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()\n"
            "assert 'atlas_reasoning' not in sys.modules\n"
            "before, first = digest()\n"
            "if sys.argv[1] == 'import':\n"
            "    from atlas_reasoning.reasoning_input_boundary import build_reasoning_input\n"
            "    pub = {'snapshot_id': 's', 'release_id': 'r', 'generated_at': GENERATED_AT, 'publication_view_version': 'v',\n"
            "           'executable_contract_version': '1.5.0', 'source': {'retrieved_at': before['source']['retrieved_at']}}\n"
            "    kept = json.dumps(before, sort_keys=True)\n"
            "    build_reasoning_input(intelligence=before, publication=pub, profiles=[])\n"
            "    assert json.dumps(before, sort_keys=True) == kept\n"
            "after, second = digest()\n"
            "print(first, second)\n"
        )
        env = {**_env(), "PYTHONPATH": str(SRC)}
        runs = {}
        for mode in ("plain", "import"):
            output = subprocess.run([sys.executable, "-c", script, mode], env=env, capture_output=True, text=True, check=True).stdout.split()
            runs[mode] = output
            self.assertEqual(output[0], output[1])
        self.assertEqual(runs["plain"], runs["import"])


class BoundaryPayloadTests(ShowcaseSite, unittest.TestCase):
    def test_payload_names_the_snapshot_and_contract_future_runs_need(self):
        intelligence, publication, profiles = self.documents()
        payload = load_reasoning_input(self.out)
        self.assertEqual(payload.snapshot.source_snapshot_id, publication["snapshot_id"])
        self.assertEqual(payload.snapshot.release_id, publication["release_id"])
        self.assertEqual(payload.snapshot.retrieved_at, intelligence["source"]["retrieved_at"])
        self.assertEqual(payload.contract.executable_contract_version, "1.5.0")
        self.assertEqual(payload.contract.intelligence_version, intelligence["intelligence_version"])
        self.assertEqual(payload.contract.boundary_version, boundary.BOUNDARY_VERSION)
        self.assertEqual([f.finding_id for f in payload.findings], [f["finding_id"] for f in intelligence["findings"]])
        self.assertEqual([e.editor_id for e in payload.editors], sorted(p["editor"]["editor_id"] for p in profiles))

    def test_payload_values_equal_the_published_documents(self):
        intelligence, _, profiles = self.documents()
        payload = load_reasoning_input(self.out)
        for row, finding in zip(intelligence["findings"], payload.findings):
            key = json.dumps
            self.assertEqual(sorted(key([s.level, s.code, thaw(s.params)], sort_keys=True) for s in finding.statements),
                             sorted(key([s["level"], s["code"], s["params"]], sort_keys=True) for s in row["statements"]))
            self.assertEqual(finding.confidence_level, row["confidence"]["level"])
            self.assertEqual(finding.sample_size, row["sample_size"])
            published = [(b["role"], b["code"], [r["monday_item_id"] for r in b["records"]])
                         for b in row["supporting_evidence"] + row["contradicting_evidence"] + row["context_evidence"]]
            self.assertEqual([(b.role, b.code, [r.monday_item_id for r in b.records]) for b in finding.evidence_blocks], published)
        by_id = {p["editor"]["editor_id"]: p for p in profiles}
        for editor in payload.editors:
            profile = by_id[editor.editor_id]
            self.assertEqual(editor.overall_status, profile["overall"]["status"])
            self.assertEqual(dict(editor.component_states), profile["overall"]["component_states"])
            self.assertEqual({c.measurement: c.difference for c in editor.recent_change},
                             {k: v["difference"] for k, v in profile["trend"]["recent_change"].items() if isinstance(v, dict)})

    def test_every_field_is_classified(self):
        classes = [boundary.ReasoningInput, boundary.UpstreamContract, boundary.SnapshotMetadata, boundary.UpstreamFinding, boundary.UpstreamStatement,
                   boundary.EvidenceBlockRef, boundary.EvidenceRecordRef, boundary.FindingScope, boundary.ParameterValue, boundary.EditorState,
                   boundary.RecentChangeValue]
        for cls in classes:
            for name, kind in field_kinds(cls).items():
                self.assertIn(kind, (*FIELD_KINDS, BY_STATEMENT_LEVEL), f"{cls.__name__}.{name}")
        self.assertEqual(field_kinds(boundary.EvidenceRecordRef)["event_ids"], boundary.SOURCE_FACT)
        self.assertEqual(field_kinds(boundary.SnapshotMetadata)["source_snapshot_id"], boundary.SNAPSHOT_METADATA)
        self.assertEqual(field_kinds(boundary.UpstreamContract)["executable_contract_version"], boundary.CONTRACT_METADATA)
        payload = load_reasoning_input(self.out)
        for finding in payload.findings:
            self.assertTrue(all(s.level == "fact" for s in finding.source_facts))
            self.assertTrue(all(s.level in ("metric", "pattern", "association") for s in finding.derived_values))
            self.assertTrue(all(s.level in ("interpretation", "hypothesis") for s in finding.upstream_interpretations))

    def test_payload_is_deeply_immutable(self):
        payload = load_reasoning_input(self.out)
        finding = payload.findings[0]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            payload.findings = ()  # type: ignore[misc]
        with self.assertRaises(dataclasses.FrozenInstanceError):
            finding.direction = "favourable"  # type: ignore[misc]
        with self.assertRaises(TypeError):
            finding.derived_values[0].params["late"] = 0  # type: ignore[index]
        with self.assertRaises(TypeError):
            payload.editors[0].component_states["deadline"] = "positive"  # type: ignore[index]
        with self.assertRaises(AttributeError):
            finding.supporting_evidence[0].records.append(None)  # type: ignore[attr-defined]
        record = finding.supporting_evidence[0].records[0]
        with self.assertRaises(TypeError):
            record.values["deadline_result"] = "on_time"  # type: ignore[index]
        copy_ = payload.to_dict()
        copy_["findings"][0]["direction"] = "changed"
        copy_["editors"][0]["component_states"]["deadline"] = "changed"
        self.assertNotEqual(payload.findings[0].direction, "changed")
        self.assertNotEqual(payload.editors[0].component_states.get("deadline"), "changed")

    def test_building_never_mutates_or_aliases_upstream_documents(self):
        intelligence, publication, profiles = self.documents()
        kept = copy.deepcopy((intelligence, publication, profiles))
        payload = build_reasoning_input(intelligence=intelligence, publication=publication, profiles=profiles)
        self.assertEqual((intelligence, publication, profiles), kept, "building the boundary changed an upstream document")
        intelligence["findings"][0]["direction"] = "tampered"
        intelligence["findings"][0]["statements"][0]["params"]["tampered"] = True
        profiles[0]["overall"]["status"] = "tampered"
        profiles[0]["overall"]["component_states"]["deadline"] = "tampered"
        profiles[0]["trend"]["recent_change"]["late_rate"]["difference"] = 99
        self.assertNotEqual(payload.findings[0].direction, "tampered")
        self.assertNotIn("tampered", payload.findings[0].statements[0].params)
        editor = payload.editor(profiles[0]["editor"]["editor_id"])
        assert editor is not None
        self.assertNotEqual(editor.overall_status, "tampered")
        self.assertNotEqual(editor.component_states["deadline"], "tampered")
        self.assertNotIn(99, [c.difference for c in editor.recent_change])

    def test_published_files_are_untouched_by_loading(self):
        before = _hashes(self.out)
        load_reasoning_input(self.out)
        self.assertEqual(_hashes(self.out), before)

    def test_building_is_deterministic(self):
        self.assertEqual(load_reasoning_input(self.out).to_dict(), load_reasoning_input(self.out).to_dict())


class BoundaryRefusalTests(ShowcaseSite, unittest.TestCase):
    def test_review_mode_never_crosses_the_boundary(self):
        intelligence, publication, profiles = self.documents()
        intelligence = {**intelligence, "mode": "review", "publishable": False}
        with self.assertRaises(ReasoningInputError):
            build_reasoning_input(intelligence=intelligence, publication=publication, profiles=profiles)

    def test_missing_or_invalid_intelligence_is_refused(self):
        intelligence, publication, profiles = self.documents()
        with self.assertRaises(ReasoningInputUnavailable):
            build_reasoning_input(intelligence=None, publication=publication, profiles=profiles)
        broken = copy.deepcopy(intelligence)
        del broken["findings"][0]["supporting_evidence"]
        with self.assertRaises(ReasoningInputError):
            build_reasoning_input(intelligence=broken, publication=publication, profiles=profiles)

    def test_documents_from_different_snapshots_or_contracts_are_refused(self):
        intelligence, publication, profiles = self.documents()
        for bad in ({**publication, "source": {**publication["source"], "retrieved_at": "2020-01-01T00:00:00Z"}},
                    {**publication, "executable_contract_version": "1.4.0"}, {**publication, "snapshot_id": ""}, None):
            with self.subTest(publication=bad and {k: bad[k] for k in ("snapshot_id", "executable_contract_version")}), \
                    self.assertRaises(ReasoningInputError):
                build_reasoning_input(intelligence=intelligence, publication=bad, profiles=profiles)
        foreign = copy.deepcopy(profiles[0])
        foreign["publication"]["snapshot_id"] = "snapshot-other"
        with self.assertRaises(ReasoningInputError):
            build_reasoning_input(intelligence=intelligence, publication=publication, profiles=[foreign])


if __name__ == "__main__":
    unittest.main()
