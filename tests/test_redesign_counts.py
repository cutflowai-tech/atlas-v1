"""Redesign T1.5 (ATLAS-DATA-002): the overview and Data & rules state the published findings with explicit, reconciled scopes."""

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atlas_commander import profile_cli
from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.investigation import site
from atlas_commander.runtime import load_contract_version
from atlas_commander.web import intel

CONTRACT = load_contract_version("1.5.0")


def numbers(html: str) -> list[int]:
    return [int(n) for n in re.findall(r'<data value="(\d+)">', html)]


class FindingCountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="atlas-redesign-counts-"))
        result = profile_cli.reconstruct_extract(showcase_extract(), CONTRACT)
        with mock.patch.object(site, "enabled", return_value=True):
            profile_cli.build_all(result, CONTRACT, cls.out, GENERATED_AT)
        cls.doc = json.loads((cls.out / site.INTELLIGENCE_JSON).read_text())
        cls.pages = {loc: (cls.out / f"{loc}/dashboard.html").read_text(encoding="utf-8") for loc in ("en", "ar")}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_the_three_scopes_add_up_to_every_published_finding(self):
        scope = intel.finding_scope(self.doc)
        ids = [f["finding_id"] for part in scope.values() for f in part]
        self.assertEqual(sorted(ids), sorted(f["finding_id"] for f in self.doc["findings"]))
        self.assertEqual(len(ids), len(set(ids)))

    def test_both_pages_state_the_same_reconciled_numbers_in_both_languages(self):
        scope = {key: len(value) for key, value in intel.finding_scope(self.doc).items()}
        total = len(self.doc["findings"])
        for html in self.pages.values():
            note = re.search(r'<p class="note" data-scope="published">(.*?)</p>', html, re.DOTALL).group(1)
            self.assertEqual(numbers(note), [total, scope["top"], scope["listed"], scope["grouped"]])
            rules = html.split('data-section="intelligence-rules"')[1].split("</dl>")[0]
            self.assertEqual(numbers(rules)[:4], [total, scope["top"], scope["listed"], scope["grouped"]])


if __name__ == "__main__":
    unittest.main()
