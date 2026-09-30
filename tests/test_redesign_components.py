"""Redesign Phase 3: the components of ``web/verdict_ui`` in both languages (unit checks and, with Chrome, rendered checks on the
dev-only component page)."""

import re
import unittest

from browser_harness import chrome, run_scenario
from verdict_fixture import editor, verdicts

from atlas_commander.i18n import AR, EN, Html
from atlas_commander.verdict.config import load_config
from atlas_commander.verdict.inputs import late_tone, speed_reading
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


class LateBarTests(unittest.TestCase):
    """T3.3."""

    def test_team_average_in_the_accessible_text_and_tooltip(self):
        bar = ui.late_bar(0.857, 0.589, "bad", EN, late=12, classifiable=14)
        self.assertIn('aria-label="Late on 86% of projects (12 of 14). Team average 59%."', bar)
        self.assertIn('title="Team average 59%"', bar)
        self.assertIn('aria-label="متأخر في 86% من المشاريع (12 من 14). متوسط الفريق 59%."', ui.late_bar(0.857, 0.589, "bad", AR, late=12, classifiable=14))

    def test_fill_marker_and_rounding(self):
        for rate, width in ((0.0, 0), (0.55, 55), (0.857, 86), (1.0, 100)):
            self.assertIn(f'class="v-late-fill" style="inline-size:{width}%"', ui.late_bar(rate, 0.589, "good", EN))
        self.assertIn('inset-inline-start:59%', ui.late_bar(0.5, 0.589, "good", EN))
        self.assertEqual((ui.whole_pct(0.545), ui.whole_pct(0.5449), ui.whole_pct(0.589)), (55, 54, 59))
        self.assertIn("No deadline data", ui.late_bar(None, 0.589, "neutral", EN))
        with self.assertRaises(ValueError):
            ui.late_bar(0.5, 0.589, "red", EN)

    def test_the_engine_decides_the_tone(self):
        config = load_config()
        self.assertEqual(late_tone(0.689, 0.589, config), "warn")            # exactly 10 points above: not yet bad
        self.assertEqual(late_tone(0.6891, 0.589, config), "bad")
        self.assertEqual(late_tone(0.5891, 0.589, config), "warn")
        self.assertEqual(late_tone(0.589, 0.589, config), "good")
        self.assertEqual(late_tone(None, 0.589, config), "neutral")
        tones = {e["display_name"]: e["metrics"]["late_tone"] for e in verdicts()["editors"]}
        self.assertEqual((tones["Refaat"], tones["Sobhy"], tones["Will"], tones["Samra"]), ("bad", "warn", "good", "neutral"))


class LabelTests(unittest.TestCase):
    """T3.4."""

    def test_speed_pill_texts(self):
        self.assertIn("<bdi dir=\"ltr\">23%</bdi> faster", ui.speed_pill(-23.3, "faster", "good", EN))
        self.assertIn('data-tone="bad" data-band="slower"><bdi dir="ltr">43%</bdi> slower', ui.speed_pill(43.1, "slower", "bad", EN))
        self.assertIn("أبطأ بنسبة <bdi dir=\"ltr\">43%</bdi>", ui.speed_pill(43.1, "slower", "bad", AR))
        self.assertIn(">Same as team<", ui.speed_pill(2.8, "same", "neutral", EN))
        self.assertIn("No speed comparison", ui.speed_pill(None, None, "neutral", EN))

    def test_the_engine_reads_the_speed(self):
        config = load_config()
        self.assertEqual(speed_reading(-23.3, True, config), {"speed_band": "faster", "speed_tone": "good"})
        self.assertEqual(speed_reading(30.0, True, config), {"speed_band": "slower", "speed_tone": "warn"})     # warn up to 30%
        self.assertEqual(speed_reading(30.1, True, config), {"speed_band": "slower", "speed_tone": "bad"})
        self.assertEqual(speed_reading(4.9, True, config), {"speed_band": "same", "speed_tone": "neutral"})     # under 5%
        self.assertEqual(speed_reading(-5.0, True, config), {"speed_band": "faster", "speed_tone": "good"})
        self.assertEqual(speed_reading(43.0, False, config), {"speed_band": "slower", "speed_tone": "neutral"})  # not classified: not judged
        self.assertEqual(speed_reading(None, False, config), {"speed_band": None, "speed_tone": "neutral"})
        readings = {e["display_name"]: (e["metrics"]["speed_band"], e["metrics"]["speed_tone"]) for e in verdicts()["editors"]}
        self.assertEqual((readings["Will"], readings["Refaat"], readings["Anas"], readings["Mohamed Mansour (Office)"], readings["Samra"]),
                         (("faster", "good"), ("slower", "bad"), ("slower", "warn"), ("same", "neutral"), (None, "neutral")))

    def test_tier_chip_always_has_its_label(self):
        for tier, text in zip(ui.TIERS, ("Best", "Steady", "Watch", "Weakest", "Low activity"), strict=True):
            chip = ui.tier_chip(tier, EN)
            self.assertIn(f'data-tier="{tier}"', chip)
            self.assertIn(f"<span>{text}</span>", chip)
        self.assertIn("<span>الأضعف</span>", ui.tier_chip("weakest", AR))
        with self.assertRaises(ValueError):
            ui.tier_chip("top", EN)

    def test_confidence_tag_only_low_on_cards_every_level_in_profiles(self):
        self.assertEqual((ui.confidence_tag("high", EN), ui.confidence_tag("medium", EN)), ("", ""))
        self.assertIn("Low confidence", ui.confidence_tag("low", EN))
        self.assertIn("ثقة منخفضة", ui.confidence_tag("low", AR))
        self.assertIn("Confidence: High", ui.confidence_tag("high", EN, in_profile=True))
        self.assertIn("الثقة: متوسطة", ui.confidence_tag("medium", AR, in_profile=True))


LATE_CHECK = """
    await wait(300);
    return [...document.querySelectorAll('#late-bar .v-late-track')].map(t => {
      const r = t.getBoundingClientRect(), f = t.querySelector('.v-late-fill').getBoundingClientRect(), m = t.querySelector('.v-late-team').getBoundingClientRect();
      const start = getComputedStyle(t).direction === 'rtl' ? r.right : r.left, sign = getComputedStyle(t).direction === 'rtl' ? -1 : 1;
      return {fill: Math.round(f.width / r.width * 100), fillStart: Math.round(Math.abs((sign > 0 ? f.left : f.right) - start)),
              marker: Math.round(sign * ((m.left + m.width / 2) - start) / r.width * 100)};
    });
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class LateBarRenderTests(unittest.TestCase):
    def test_0_55_86_100_in_both_directions(self):
        for loc in (EN, AR):
            bars = run_scenario(render_components(loc), LATE_CHECK, width=900, height=900)
            self.assertEqual([b["fill"] for b in bars[:4]], [0, 55, 86, 100], (loc, bars))
            self.assertTrue(all(b["fillStart"] <= 1 for b in bars), (loc, bars))      # every bar grows from the inline start
            self.assertTrue(all(58 <= b["marker"] <= 60 for b in bars), (loc, bars))  # the team marker at 59% from the inline start


class PersonCardTests(unittest.TestCase):
    """T3.5."""

    def card(self, name="Refaat", loc=EN):
        verdict = editor(verdicts(), name)
        return verdict, ui.person_card(verdict, Html("The weakest this month."), loc)

    def test_one_link_to_the_profile_with_every_part(self):
        verdict, card = self.card()
        self.assertTrue(card.startswith(f'<a class="v-card" href="#/editor/{verdict["editor_id"]}"'))
        self.assertEqual(len(re.findall(r"<(a|button|input|select|textarea)\b", card)), 1)       # the card is the only interactive element
        for part in ('class="v-av s56"', 'data-tier="weakest"', '<bdi dir="ltr">8</bdi>', "The weakest this month.", 'class="v-late"',
                     'class="v-pill v-speed"', "14</data> this month", "1</data> in progress"):
            self.assertIn(part, card)
        self.assertNotIn("Low confidence", card)                                               # Refaat is Medium

    def test_low_confidence_shows_and_arabic_labels(self):
        _, card = self.card("Sobhy", AR)
        self.assertIn("ثقة منخفضة", card)
        for label in ("التأخير", "السرعة", "المشاريع", "هذا الشهر"):
            self.assertIn(label, card)


CARD_CHECK = """
    await wait(300);
    const card = document.querySelector('#cards .v-card');
    card.focus();
    const before = getComputedStyle(card).outlineStyle;
    document.body.focus();
    // keyboard focus: Tab from the start of the page reaches the first card
    const links = [...document.querySelectorAll('a[href], button')];
    return {focusable: links.indexOf(card) >= 0, outlineOnFocus: before, width: Math.round(card.getBoundingClientRect().width),
            overflow: [...document.querySelectorAll('#cards .v-card')].some(c => c.scrollWidth > c.clientWidth + 1)};
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class PersonCardRenderTests(unittest.TestCase):
    def test_focus_is_visible_and_nothing_overflows(self):
        for loc in (EN, AR):
            result = run_scenario(render_components(loc), CARD_CHECK, width=1440, height=900)
            self.assertTrue(result["focusable"], result)
            self.assertEqual(result["outlineOnFocus"], "solid", result)     # :focus-visible after programmatic focus in headless Chrome
            self.assertFalse(result["overflow"], result)


class DecisionCardTests(unittest.TestCase):
    """T3.6."""

    def test_owners_open_profiles_and_roles_are_named(self):
        document = verdicts()
        editors = {e["editor_id"]: e for e in document["editors"]}
        today, weakest, scheduling, ask, management = document["decisions"]
        card = ui.decision_card(today, Html("3 overdue"), editors, EN)
        self.assertIn('data-horizon="today"', card)
        self.assertIn(">Today<", card)
        self.assertEqual(re.findall(r'class="v-dec-face" href="#/editor/([^"]+)"', card), today["owner_editor_ids"])
        self.assertIn("Owner: Editors manager", ui.decision_card(weakest, Html("plan"), editors, EN))
        self.assertIn("المسؤول: مسؤول الجدولة", ui.decision_card(scheduling, Html("runway"), editors, AR))
        self.assertIn(">اسأل<", ui.decision_card(ask, Html("ask"), editors, AR))
        rule = ui.decision_card(management, Html("rule"), editors, EN)
        self.assertIn("Management decision", rule)
        self.assertIn("Owner: CEO", rule)
        self.assertNotIn("v-dec-face", rule)
        with self.assertRaises(ValueError):
            ui.decision_card(dict(today, horizon="soon"), Html("x"), editors, EN)


DECISION_CHECK = """
    await wait(300);
    return [...document.querySelectorAll('#decisions .v-dec')].map(d => {
      const cs = getComputedStyle(d);
      return {horizon: d.dataset.horizon, left: cs.borderLeftWidth, right: cs.borderRightWidth, color: cs.direction === 'rtl' ? cs.borderRightColor : cs.borderLeftColor,
              faces: d.querySelectorAll('a.v-dec-face').length};
    });
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class DecisionCardRenderTests(unittest.TestCase):
    def test_four_horizon_colours_on_the_inline_start_stripe(self):
        for loc, side in ((EN, "left"), (AR, "right")):
            cards = run_scenario(render_components(loc), DECISION_CHECK, width=900, height=900)
            self.assertEqual([c["horizon"] for c in cards], ["today", "this_week", "this_week", "ask", "management"])
            self.assertTrue(all(c[side] == "4px" for c in cards), (loc, cards))
            colours = {c["horizon"]: c["color"] for c in cards}
            self.assertEqual(len(set(colours.values())), 4, colours)
            self.assertEqual([c["faces"] for c in cards], [3, 1, 0, 2, 0])


class ComponentPageTests(unittest.TestCase):
    def test_the_page_is_self_contained_and_localised(self):
        for loc in (EN, AR):
            html = render_components(loc)
            self.assertTrue(html.startswith(f'<!doctype html><html lang="{loc.code}" dir="{"rtl" if loc.code == "ar" else "ltr"}">'))
            self.assertNotRegex(html, r'(src|href)="https?://')
            self.assertEqual(re.findall(r'aria-label="[^"]*\{', html), [])


if __name__ == "__main__":
    unittest.main()
