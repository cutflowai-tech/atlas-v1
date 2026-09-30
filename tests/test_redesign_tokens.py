"""Redesign T3.1: the handoff's colour tokens (dark and light) and font stacks are global in the design system, and change nothing
on the current pages."""

import re
import unittest

from redesign_site import page

from atlas_commander.web.style import CSS

# 01-PRODUCT-DIRECTION.md "Visual design": token -> (dark, light)
HANDOFF = {"bg": ("#111419", "#f5f4f0"), "surface": ("#191d24", "#ffffff"), "raise": ("#21262f", "#efede7"), "line": ("#2b313c", "#e1ded5"),
           "fg": ("#eceef2", "#1a1d23"), "muted": ("#9aa3b2", "#596070"), "faint": ("#6b7484", "#8a909b"), "accent": ("#e7c46a", "#946600"),
           "good": ("#7fcf9f", "#2d7a4d"), "info": ("#8fb4ea", "#2d5c9a"), "warn": ("#e7c46a", "#946600"), "bad": ("#ef8a73", "#b64a31"),
           "idle": ("#7d8594", "#7a808b")}


def _declarations(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z0-9_-]+):([^;}]+)", block))


def _hex(value: str) -> str:
    value = value.strip().lower()
    return "#" + "".join(c * 2 for c in value[1:]) if re.fullmatch(r"#[0-9a-f]{3}", value) else value


LIGHT = _declarations(re.search(r":root\{color-scheme:light dark;(.*?)\}", CSS, re.DOTALL).group(1))
DARK = _declarations(re.search(r"@media \(prefers-color-scheme:dark\)\{:root\{(.*?)\}\}", CSS, re.DOTALL).group(1))


class TokenTests(unittest.TestCase):
    def test_every_handoff_colour_in_both_schemes(self):
        for name, (dark, light) in HANDOFF.items():
            self.assertEqual(_hex(LIGHT[f"v-{name}"]), light, name)
            self.assertEqual(_hex(DARK[f"v-{name}"]), dark, name)

    def test_tiers_and_horizons_have_a_semantic_colour(self):
        for tier, colour in {"best": "good", "steady": "info", "watch": "warn", "weakest": "bad", "low_activity": "idle"}.items():
            self.assertEqual(LIGHT[f"v-tier-{tier}"], f"var(--v-{colour})")
        for horizon, colour in {"today": "bad", "this_week": "warn", "ask": "idle", "management": "info"}.items():
            self.assertEqual(LIGHT[f"v-horizon-{horizon}"], f"var(--v-{colour})")

    def test_font_stacks_lead_with_the_handoff_fonts_and_fall_back_without_downloading(self):
        self.assertTrue(LIGHT["v-display"].startswith('"Readex Pro",'))
        self.assertTrue(LIGHT["v-body"].startswith('"IBM Plex Sans Arabic",'))
        self.assertTrue(LIGHT["v-num"].startswith('"IBM Plex Mono",'))
        for stack in ("v-display", "v-body"):
            self.assertTrue(LIGHT[stack].endswith("var(--font)"), stack)       # the existing system stacks (Arabic ones on Arabic pages)
        self.assertTrue(LIGHT["v-num"].endswith("var(--mono)"))
        self.assertNotIn("@font-face", CSS)
        self.assertNotRegex(CSS, r"url\(")

    def test_the_existing_tokens_keep_their_values(self):
        # the handoff reuses names such as bg, line and good with other values; prefixed, they cannot change the current pages
        self.assertLessEqual({"bg", "surface", "line", "good"}, set(LIGHT))
        self.assertEqual((LIGHT["bg"], DARK["bg"], LIGHT["line"], LIGHT["surface"]), ("#f4f3ef", "#121310", "#e3e0d7", "#fff"))

    def test_both_locales_carry_the_tokens(self):
        for locale in ("en", "ar"):
            self.assertIn("--v-tier-weakest:var(--v-bad)", page(locale))


if __name__ == "__main__":
    unittest.main()
