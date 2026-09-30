"""Redesign Phase 3: the components of ``web/verdict_ui`` in both languages (unit checks and, with Chrome, rendered checks on the
dev-only component page)."""

import re
import unittest

from browser_harness import chrome, run_scenario

from atlas_commander.i18n import AR, EN
from atlas_commander.web import verdict_ui as ui
from atlas_commander.web.components import render_components


class AvatarTests(unittest.TestCase):
    """T3.2."""

    def test_initials(self):
        self.assertEqual(ui.initial("Will"), "W")
        self.assertEqual(ui.initial("mohamed Mansour (Office)"), "M")
        self.assertEqual(ui.initial("إسلام"), "إس")                     # names starting with إ or ا: the first two letters
        self.assertEqual(ui.initial("احمد"), "اح")
        self.assertEqual(ui.initial("سمرا"), "س")
        self.assertEqual(ui.initial("  "), "?")

    def test_colour_is_stable_per_editor(self):
        self.assertEqual(ui.hue("editor-label-11"), ui.hue("editor-label-11"))
        self.assertGreater(len({ui.hue(f"editor-label-{i}") for i in range(20)}), 10)

    def test_accessible_name_in_both_languages(self):
        html = ui.avatar("editor-label-11", "Refaat", EN, tier="weakest", rank=8, ranked_of=8)
        self.assertIn('role="img" aria-label="Refaat, Weakest, rank 8 of 8"', html)
        self.assertIn('aria-label="Refaat، الأضعف، الترتيب 8 من 8"', ui.avatar("editor-label-11", "Refaat", AR, tier="weakest", rank=8, ranked_of=8))
        self.assertIn('aria-label="Samra, Low activity"', ui.avatar("editor-label-8", "Samra", EN, tier="low_activity"))
        self.assertIn('aria-label="Samra"', ui.avatar("editor-label-8", "Samra", EN))

    def test_sizes_rank_photo(self):
        for size in (28, 56, 96):
            self.assertIn(f'class="v-av s{size}"', ui.avatar("x", "Will", EN, size=size))
        with self.assertRaises(ValueError):
            ui.avatar("x", "Will", EN, size=40)
        self.assertNotIn("v-av-rank", ui.avatar("x", "Samra", EN, tier="low_activity"))
        self.assertIn('<bdi dir="ltr">3</bdi>', ui.avatar("x", "Will", EN, tier="best", rank=3, ranked_of=8))
        photo = ui.avatar("x", "Will", EN, photo_url='https://example.org/a"b.jpg')
        self.assertIn('src="https://example.org/a&quot;b.jpg" alt="" loading="lazy"', photo)
        self.assertIn('onerror="this.remove()"', photo)
        self.assertRegex(photo, r'<span class="v-av-i" aria-hidden="true"><bdi>W</bdi></span><img')   # the initial is always underneath


AVATAR_CHECK = """
    await wait(400);
    const boxes = [...document.querySelectorAll('#avatar .v-av')];
    const size = s => boxes.filter(b => b.classList.contains('s' + s)).map(b => Math.round(b.getBoundingClientRect().width));
    const photos = [...document.querySelectorAll('#avatar .row:last-child .v-av')];   // photo, broken photo, no tier
    return {s28: size(28), s56: size(56), s96: size(96), withImage: photos.map(p => !!p.querySelector('img')),
            loaded: photos[0].querySelector('img') ? photos[0].querySelector('img').naturalWidth > 0 : false,
            initialShown: getComputedStyle(photos[1].querySelector('.v-av-i')).visibility,
            ring: getComputedStyle(document.querySelector('#avatar .v-av[data-tier=weakest]')).boxShadow,
            badgeSide: (() => { const a = document.querySelector('#avatar .v-av.s96[data-tier=best]'); const r = a.getBoundingClientRect(), b = a.querySelector('.v-av-rank').getBoundingClientRect(); return b.left + b.width / 2 > r.left + r.width / 2 ? 'right' : 'left'; })(),
            overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth};
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class AvatarRenderTests(unittest.TestCase):
    def test_sizes_fallback_ring_and_direction(self):
        for loc, side in ((EN, "right"), (AR, "left")):
            result = run_scenario(render_components(loc), AVATAR_CHECK, width=900, height=800)
            self.assertEqual(set(result["s28"]), {28}, result)
            self.assertEqual(set(result["s56"]), {56}, result)
            self.assertEqual(set(result["s96"]), {96}, result)
            self.assertEqual(result["withImage"], [True, False, False], result)   # the broken photo removed itself
            self.assertTrue(result["loaded"], result)
            self.assertEqual(result["initialShown"], "visible", result)
            self.assertRegex(result["ring"], r"rgb", result)
            self.assertEqual(result["badgeSide"], side, result)                    # the rank badge sits at the inline end
            self.assertEqual(result["overflow"], 0, result)


class ComponentPageTests(unittest.TestCase):
    def test_the_page_is_self_contained_and_localised(self):
        for loc in (EN, AR):
            html = render_components(loc)
            self.assertTrue(html.startswith(f'<!doctype html><html lang="{loc.code}" dir="{"rtl" if loc.code == "ar" else "ltr"}">'))
            self.assertNotRegex(html, r'(src|href)="https?://')
            self.assertEqual(re.findall(r'aria-label="[^"]*\{', html), [])


if __name__ == "__main__":
    unittest.main()
