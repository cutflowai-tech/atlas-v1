"""Redesign T6.3: the rendered overview's numbers equal the snapshot's (``python3 -m atlas_commander.web.verify <site>``)."""

import contextlib
import io
import unittest

from redesign_site import document, page, site

from atlas_commander.verdict.site import VERDICTS_JSON
from atlas_commander.web import verify


class VerifyTests(unittest.TestCase):
    def test_the_showcase_build_matches_its_snapshot(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify.main([str(site())])
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("numbers match the snapshot", out.getvalue())

    def test_a_changed_number_is_found(self):
        verdicts = document(VERDICTS_JSON)
        html = page("en")
        target = next(v for v in verdicts["editors"] if v["metrics"]["late_rate"] is not None)
        late = verify._pct(target["metrics"]["late_rate"] * 100)
        card_start = html.index(f'<a class="v-card" href="#/editor/{target["editor_id"]}"')
        shown = f'<bdi dir="ltr">{late}%</bdi>'
        at = html.index(shown, card_start)
        changed = html[:at] + f'<bdi dir="ltr">{late + 1}%</bdi>' + html[at + len(shown):]
        _, problems = verify.verify(changed, verdicts)
        self.assertTrue(any(target["display_name"] in p and "late" in p for p in problems), problems)
        rail = changed.replace('<aside class="v-rail"', '<aside class="v-rail" data-x', 1)
        reordered = {**verdicts, "decisions": list(reversed(verdicts["decisions"]))}
        self.assertTrue(len(verdicts["decisions"]) < 2 or any("rail" in p for p in verify.verify(rail, reordered)[1]))


if __name__ == "__main__":
    unittest.main()
