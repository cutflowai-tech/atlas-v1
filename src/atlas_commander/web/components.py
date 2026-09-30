"""Development-only component page of the redesign (Phase 3: "a dev-only /dev/components page" when there is no Storybook).

    PYTHONPATH=src python3 -m atlas_commander.web.components out/dev

writes ``out/dev/components/en.html`` and ``ar.html``: every state of every ``web/verdict_ui`` component, on the site's stylesheet.
Open them in light and dark mode (the page follows the system scheme, like the app). The values are made-up samples chosen to show
each state; they are never published (the site build does not include this page, and nginx serves only ``/``, ``/en/``, ``/ar/``).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from html import escape
from pathlib import Path
from typing import Any

from atlas_commander import site_layout
from atlas_commander.i18n import Html, Loc, locales
from atlas_commander.web import verdict_ui as ui
from atlas_commander.web.style import CSS

# A photo that exists (an inline SVG, so the page makes no network request) and one that does not load.
SAMPLE_PHOTO = ("data:image/svg+xml;utf8," + "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'%3E%3Cdefs%3E%3ClinearGradient id='g' x2='1' y2='1'%3E"
                "%3Cstop offset='0' stop-color='%23c9a26b'/%3E%3Cstop offset='1' stop-color='%234a6fa5'/%3E%3C/linearGradient%3E%3C/defs%3E"
                "%3Crect width='10' height='10' fill='url(%23g)'/%3E%3C/svg%3E")
BROKEN_PHOTO = "data:image/png;base64,bm90LWFuLWltYWdl"
SAMPLE_EDITORS = [("sample-1", "Layla"), ("sample-2", "إسلام"), ("sample-3", "احمد"), ("sample-4", "Sample Editor (Office)")]
PAGE_CSS = """
.cp{max-width:1280px;margin:0 auto;padding:24px 16px 64px;font-family:var(--v-body);background:var(--v-bg);color:var(--v-fg)}
body{background:var(--v-bg)}.cp h1{font:600 22px/1.3 var(--v-display);margin-bottom:4px}.cp>p{color:var(--v-muted);margin:0 0 24px}
.cp section{border-top:1px solid var(--v-line);padding:20px 0}.cp h2{font:600 16px/1.4 var(--v-display);margin-bottom:12px;unicode-bidi:plaintext}
.cp .row{display:flex;flex-wrap:wrap;align-items:center;gap:20px;margin-bottom:14px}.cp .cap{font-size:12px;color:var(--v-faint);margin-inline-end:8px;min-width:120px}
"""


def _row(caption: str, items: Sequence[str]) -> str:
    return f'<div class="row"><span class="cap" dir="ltr">{escape(caption)}</span>{"".join(items)}</div>'


def avatar_section(loc: Loc) -> str:
    rows = []
    for size in ui.AVATAR_SIZES:
        rows.append(_row(f"{size} px · tiers", [ui.avatar(editor_id, name, loc, size=size, tier=tier, rank=rank, ranked_of=9)
                                               for (editor_id, name), tier, rank in zip(SAMPLE_EDITORS * 2, ("best", "steady", "watch", "weakest", "low_activity"),
                                                                                         (1, 4, 6, 9, None), strict=False)]))
    rows.append(_row("photo · broken photo · no tier", [ui.avatar("sample-1", "Layla", loc, size=96, tier="best", rank=1, ranked_of=9, photo_url=SAMPLE_PHOTO),
                                                        ui.avatar("sample-2", "إسلام", loc, size=96, tier="watch", rank=6, ranked_of=9, photo_url=BROKEN_PHOTO),
                                                        ui.avatar("sample-4", "Sample Editor (Office)", loc, size=56)]))
    return f'<section id="avatar"><h2>Avatar (T3.2)</h2>{"".join(rows)}</section>'


def late_section(loc: Loc) -> str:
    team = 0.589
    rows = [_row(f"{ui.whole_pct(rate)}% · {tone}", [f'<div style="inline-size:320px">{ui.late_bar(rate, team, tone, loc, late=late, classifiable=n)}</div>'])
            for rate, tone, late, n in ((0.0, "good", 0, 12), (0.55, "good", 11, 20), (0.857, "bad", 12, 14), (1.0, "bad", 2, 2), (0.62, "warn", 13, 21))]
    rows.append(_row("no late rate", [f'<div style="inline-size:320px">{ui.late_bar(None, team, "neutral", loc)}</div>']))
    return f'<section id="late-bar"><h2>LateBar (T3.3) · team average 59%</h2>{"".join(rows)}</section>'


def labels_section(loc: Loc) -> str:
    speeds = [ui.speed_pill(-23.3, "faster", "good", loc), ui.speed_pill(12.0, "slower", "warn", loc), ui.speed_pill(30.0, "slower", "warn", loc),
              ui.speed_pill(43.1, "slower", "bad", loc), ui.speed_pill(2.8, "same", "neutral", loc), ui.speed_pill(-8.0, "faster", "neutral", loc),
              ui.speed_pill(None, None, "neutral", loc)]
    rows = [_row("SpeedPill", speeds),
            _row("TierChip", [ui.tier_chip(tier, loc) for tier in ui.TIERS]),
            _row("Confidence · card", [ui.confidence_tag(level, loc) or '<span class="cap">(hidden)</span>' for level in ui.CONFIDENCE]),
            _row("Confidence · profile", [ui.confidence_tag(level, loc, in_profile=True) for level in ui.CONFIDENCE])]
    return f'<section id="labels"><h2>SpeedPill, TierChip, ConfidenceTag (T3.4)</h2>{"".join(rows)}</section>'


def _sample(editor_id: str, name: str, tier: str, rank: int | None, confidence: str, late: tuple[int, int] | None, speed: tuple[float, str, str] | None,
            completed: int, active: int) -> dict:
    return {"editor_id": editor_id, "display_name": name, "tier": tier, "rank": rank, "ranked_of": 8, "confidence": confidence, "photo_url": None,
            "metrics": {"late_rate": late[0] / late[1] if late else None, "late_count": late[0] if late else None, "deadline_classifiable": late[1] if late else 0,
                        "team_late_rate": 0.589, "late_tone": ("bad" if late and late[0] / late[1] > 0.689 else "warn" if late and late[0] / late[1] > 0.589 else "good") if late else "neutral",
                        "speed_delta_pct": speed[0] if speed else None, "speed_band": speed[1] if speed else None, "speed_tone": speed[2] if speed else "neutral",
                        "completed": completed, "active": active}}


CARD_SAMPLES = [
    (_sample("sample-1", "Layla", "best", 1, "medium", (6, 20), (-23.0, "faster", "good"), 20, 2),
     "Best this month: the highest load, faster than peers, and late less often."),
    (_sample("sample-3", "احمد", "weakest", 8, "medium", (12, 14), (43.0, "slower", "bad"), 14, 1),
     "The weakest this month: late on 86% of projects, slower than peers and than their own history. Scheduling does not explain it."),
    (_sample("sample-4", "Sample Editor (Office)", "low_activity", None, "low", (1, 2), (2.8, "same", "neutral"), 2, 1),
     "Low activity: 2 projects this month."),
    (_sample("sample-2", "إسلام", "low_activity", None, "low", None, None, 0, 0), "No projects this month and nothing in progress."),
]


def cards_section(loc: Loc) -> str:
    cards = "".join(f'<div style="inline-size:320px">{ui.person_card(v, Html(escape(text)), loc)}</div>' for v, text in CARD_SAMPLES)
    return f'<section id="cards"><h2>PersonCard (T3.5) · sample sentences in English until T4.1</h2><div class="row" style="align-items:stretch">{cards}</div></section>'


DECISION_OWNERS = {v["editor_id"]: v for v, _ in CARD_SAMPLES}
DECISION_SAMPLES: list[tuple[dict[str, Any], str]] = [
    ({"id": "dec-000000000001", "horizon": "today", "owner_editor_ids": ["sample-3", "sample-1", "sample-4"], "owner_role": None},
     "3 projects are past their deadline and still open. Agree a realistic delivery date."),
    ({"id": "dec-000000000002", "horizon": "this_week", "owner_editor_ids": ["sample-3"], "owner_role": "editors_manager"},
     "An improvement plan for the weakest Editor this week."),
    ({"id": "dec-000000000003", "horizon": "this_week", "owner_editor_ids": [], "owner_role": "scheduling_owner"},
     "Review how delivery dates are set: most late projects started with short runway."),
    ({"id": "dec-000000000004", "horizon": "ask", "owner_editor_ids": ["sample-2", "sample-4"], "owner_role": None},
     "No projects this month: leave or an assignment gap?"),
    ({"id": "dec-000000000005", "horizon": "management", "owner_editor_ids": [], "owner_role": "ceo"},
     "Approve the Quality rule. Atlas cannot see quality yet."),
]


def decisions_section(loc: Loc) -> str:
    cards = "".join(ui.decision_card(d, Html(escape(text)), DECISION_OWNERS, loc) for d, text in DECISION_SAMPLES)
    return (f'<section id="decisions"><h2>DecisionCard (T3.6) · all four horizons</h2>'
            f'<div style="display:grid;gap:12px;max-inline-size:360px">{cards}</div></section>')


def tiers_section(loc: Loc) -> str:
    cards = [ui.person_card(v, Html(escape(text)), loc) for v, text in CARD_SAMPLES]
    frames = "".join(f'<div class="frame" data-width="{w}" style="inline-size:{w}px;max-inline-size:100%">{ui.tier_section("best", cards[:count], loc)}</div>'
                     for w, count in ((300, 2), (600, 3), (900, 4), (1200, 4), (1200, 1)))
    return (f'<section id="tiers"><h2>TierSection (T3.7) · frames 300 / 600 / 900 / 1200 px, and a lone card</h2>{frames}'
            f'{"".join(ui.tier_section(t, cards[:1], loc) for t in ui.TIERS[1:])}</section>')


def render_components(loc: Loc) -> str:
    loc = loc.isolating()
    body = (f'<main class="cp"><h1>Atlas redesign · components</h1><p>Development only · sample values · {escape(loc.code)} · '
            f'follows the system light/dark scheme</p>{avatar_section(loc)}{late_section(loc)}{labels_section(loc)}{cards_section(loc)}{decisions_section(loc)}{tiers_section(loc)}</main>')
    return (f'{site_layout.document_opening(loc.code)}<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>Atlas components</title><style>{CSS}{PAGE_CSS}</style></head><body>{body}</body></html>')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas-components")
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    target = args.out_dir / "components"
    target.mkdir(parents=True, exist_ok=True)
    for loc in locales():
        (target / f"{loc.code}.html").write_text(render_components(loc), encoding="utf-8")
        print(target / f"{loc.code}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
