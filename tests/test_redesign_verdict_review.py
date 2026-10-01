"""Redesign T2.16: the real snapshot build publishes verdicts for every Editor, and the review script prints them (or fails)."""

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from redesign_site import document, site

from atlas_commander import site_layout
from atlas_commander.verdict import review
from atlas_commander.verdict.site import VERDICTS_JSON


def run(path: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = review.main([str(path)])
    return code, out.getvalue(), err.getvalue()


class ReviewScriptTests(unittest.TestCase):
    def copy(self) -> Path:
        target = Path(tempfile.mkdtemp(prefix="atlas-review-")) / "site"
        self.addCleanup(shutil.rmtree, target.parent, True)
        shutil.copytree(site(), target)
        return target

    def test_the_build_has_a_verdict_for_every_editor_and_the_table_lists_them(self):
        code, out, err = run(site())
        self.assertEqual((code, err), (0, ""))
        dashboard = document(site_layout.DASHBOARD_JSON)
        self.assertEqual(sorted(e["editor_id"] for e in document(VERDICTS_JSON)["editors"]), sorted(e["editor_id"] for e in dashboard["editors"]))
        header = next(line for line in out.splitlines() if line.startswith("Editor"))
        self.assertEqual(header.split(), ["Editor", "Tier", "Rank", "Score", "Confidence", "Headline", "Overdue"])
        for e in dashboard["editors"]:
            self.assertIn(e["display_name"], out)
        self.assertIn("Team: ", out)
        self.assertIn("Decisions (", out)

    def test_a_build_without_verdicts_fails(self):
        target = self.copy()
        (target / VERDICTS_JSON).unlink()
        code, _, err = run(target)
        self.assertEqual(code, 1)
        self.assertIn("missing", err)

    def test_a_missing_editor_or_another_snapshot_fails(self):
        target = self.copy()
        verdicts = json.loads((target / VERDICTS_JSON).read_text())
        verdicts["editors"] = verdicts["editors"][1:]
        (target / VERDICTS_JSON).write_text(json.dumps(verdicts))
        self.assertEqual(run(target)[0], 1)
        verdicts = document(VERDICTS_JSON) | {"source": dict(document(VERDICTS_JSON)["source"], retrieved_at="2020-01-01T00:00:00Z")}
        (target / VERDICTS_JSON).write_text(json.dumps(verdicts))
        code, _, err = run(target)
        self.assertEqual(code, 1)
        self.assertIn("snapshot", err)


if __name__ == "__main__":
    unittest.main()
