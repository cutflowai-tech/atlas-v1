"""Development-only component page of the redesign (Phase 3: "a dev-only /dev/components page" when there is no Storybook).

    PYTHONPATH=src python3 -m atlas_commander.web.components out/dev

writes ``out/dev/components/en.html`` and ``ar.html``: every state of every ``web/verdict_ui`` component, on the site's stylesheet.
Open them in light and dark mode (the page follows the system scheme, like the app). The values are made-up samples chosen to show
each state; they are never published (the site build does not include this page, and nginx serves only ``/``, ``/en/``, ``/ar/``).
"""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

from atlas_commander import site_layout
from atlas_commander.i18n import Loc, locales
from atlas_commander.web import verdict_ui as ui
from atlas_commander.web.style import CSS

# A photo that exists (an inline SVG, so the page makes no network request) and one that does not load.
SAMPLE_PHOTO = ("data:image/svg+xml;utf8," + "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'%3E%3Cdefs%3E%3ClinearGradient id='g' x2='1' y2='1'%3E"
                "%3Cstop offset='0' stop-color='%23c9a26b'/%3E%3Cstop offset='1' stop-color='%234a6fa5'/%3E%3C/linearGradient%3E%3C/defs%3E"
                "%3Crect width='10' height='10' fill='url(%23g)'/%3E%3C/svg%3E")
BROKEN_PHOTO = "data:image/png;base64,bm90LWFuLWltYWdl"
SAMPLE_EDITORS = [("sample-1", "Layla"), ("sample-2", "إسلام"), ("sample-3", "احمد"), ("sample-4", "Sample Editor (Office)")]
PAGE_CSS = """
.cp{max-width:1100px;margin:0 auto;padding:24px 16px 64px;font-family:var(--v-body);background:var(--v-bg);color:var(--v-fg)}
body{background:var(--v-bg)}.cp h1{font:600 22px/1.3 var(--v-display);margin-bottom:4px}.cp>p{color:var(--v-muted);margin:0 0 24px}
.cp section{border-top:1px solid var(--v-line);padding:20px 0}.cp h2{font:600 16px/1.4 var(--v-display);margin-bottom:12px}
.cp .row{display:flex;flex-wrap:wrap;align-items:center;gap:20px;margin-bottom:14px}.cp .cap{font-size:12px;color:var(--v-faint);margin-inline-end:8px;min-width:120px}
"""


def _row(caption: str, items: list[str]) -> str:
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


def render_components(loc: Loc) -> str:
    loc = loc.isolating()
    body = (f'<main class="cp"><h1>Atlas redesign · components</h1><p>Development only · sample values · {escape(loc.code)} · '
            f'follows the system light/dark scheme</p>{avatar_section(loc)}</main>')
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
