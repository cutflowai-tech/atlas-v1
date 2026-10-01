"""Compare the numbers a built Team overview shows with its snapshot (redesign T6.3).

    PYTHONPATH=src python3 -m atlas_commander.web.verify <site_dir>

Reads the English page (``en/dashboard.html``) and ``verdicts.json`` of the same build and checks, for every Editor, the tier section
the card sits in, the rank badge, the late-rate percentage, bar and team marker, the speed pill, the projects and work in progress, the
Low-confidence tag, every number of the one-line verdict, and in the profile drawer the four metrics and the overdue alerts; for the team, the three KPI values and tones; and
the order of the decisions in the rail. Expected values are computed from ``verdicts.json`` here, independently of the page code (whole
percentages rounded half up). Prints one line per Editor and exits 1 on any difference. Nothing is written.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from html import unescape
from pathlib import Path
from typing import Any


def _pct(value: float) -> int:
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def _between(html: str, start: str, end: str) -> str:
    return html.split(start, 1)[1].split(end, 1)[0] if start in html else ""


def card_checks(card: str, v: Mapping[str, Any]) -> list[str]:
    m, out = v["metrics"], []
    badge = re.search(r'class="v-av-rank"[^>]*><bdi dir="ltr">(\d+)</bdi>', card)
    if (int(badge.group(1)) if badge else None) != v["rank"]:
        out.append(f"rank badge {badge.group(1) if badge else None} != {v['rank']}")
    if m["late_rate"] is None:
        if "No deadline data" not in _text(card):
            out.append("missing 'No deadline data'")
    else:
        late = _pct(m["late_rate"] * 100)
        if f'<span class="v-late-v" aria-hidden="true"><bdi dir="ltr">{late}%</bdi>' not in card:
            out.append(f"late {late}% not shown")
        if f'class="v-late-fill" style="inline-size:{min(max(late, 0), 100)}%"' not in card:
            out.append(f"late bar not {late}%")
        if m["team_late_rate"] is not None and f'inset-inline-start:{_pct(m["team_late_rate"] * 100)}%' not in card:
            out.append("team marker misplaced")
        if f'data-tone="{m["late_tone"]}" role="img"' not in card:
            out.append(f"late tone not {m['late_tone']}")
    pill = _text(_between(card, 'class="v-pill v-speed"', "</span>").split(">", 1)[-1]) if 'class="v-pill v-speed"' in card else ""
    if m["speed_band"] is None:
        expected_pill = "No speed comparison"
    elif m["speed_band"] == "same":
        expected_pill = "Same as team"
    else:
        expected_pill = f"{abs(_pct(m['speed_delta_pct']))}% {m['speed_band']}"
    if pill != expected_pill:
        out.append(f"speed pill {pill!r} != {expected_pill!r}")
    text = _text(card)
    if f"{m['completed']} this month" not in text:
        out.append(f"projects {m['completed']} not shown")
    if m["active"] and m["completed"] and f"{m['active']} in progress" not in text:
        out.append(f"in progress {m['active']} not shown")
    if ("Low confidence" in text) != (v["confidence"] == "low"):
        out.append(f"confidence tag wrong for {v['confidence']}")
    sentence = _text(_between(card, '<span class="v-card-verdict">', "</span><span class=\"v-card-m\">"))
    for name, value in v["headline"]["params"].items():   # every number of the one-line verdict, as it reads
        if name == "count" and value in (1, 2):   # "One open project…": a count of one or two may be written in words
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            expected = f"{abs(_pct(value))}%" if name.endswith("_pct") else str(value)
            if expected not in sentence:
                out.append(f"verdict sentence lacks {name}={expected}")
    return out


def drawer_checks(drawer: str, v: Mapping[str, Any]) -> list[str]:
    m, out = v["metrics"], []
    values = [_text(x) for x in re.findall(r'<span class="v-metric-v">(.*?)</span><span class="v-metric-s">', drawer)]
    if len(values) != 4:
        return [f"{len(values)} metrics in the drawer"]
    if m["late_rate"] is not None and values[0] != f"{_pct(m['late_rate'] * 100)}%":
        out.append(f"drawer late {values[0]!r}")
    if m["speed_band"] not in (None, "same"):
        whole = _pct(m["speed_delta_pct"])
        expected = f"{'+' if whole > 0 else '−' if whole < 0 else ''}{abs(whole)}%"
        if values[1] != expected:
            out.append(f"drawer speed {values[1]!r} != {expected!r}")
    if values[2] != str(m["completed"]):
        out.append(f"drawer projects {values[2]!r}")
    alerts = drawer.count('class="v-prof-alert"')
    if alerts != len(v["overdue"]):
        out.append(f"{alerts} overdue alerts != {len(v['overdue'])}")
    return out


def verify(html: str, verdicts: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """(one report line per Editor, the differences)."""
    team_view = _between(html, '<div data-view="team">', '<div data-view="')
    problems, lines = [], []
    tiers = {tier: section for tier, section in re.findall(r'<section class="v-tsec" data-tier="([a-z_]+)"(.*?)</section>', team_view, flags=re.DOTALL)}
    for v in verdicts["editors"]:
        card = _between(team_view, f'<a class="v-card" href="#/editor/{v["editor_id"]}"', "</a>")
        drawer = _between(html, f'<template id="vp-{v["editor_id"]}">', "</template>")
        found = [] if card else ["no card"]
        if card and f'href="#/editor/{v["editor_id"]}"' not in tiers.get(v["tier"], ""):
            found.append(f"card not in the {v['tier']} section")
        found += card_checks(card, v) if card else []
        found += drawer_checks(drawer, v) if drawer else ["no drawer"]
        problems += [f"{v['display_name']}: {p}" for p in found]
        rank = str(v["rank"]) if v["rank"] is not None else "—"
        late = "—" if v["metrics"]["late_rate"] is None else f"{_pct(v['metrics']['late_rate'] * 100)}%"
        verdict = "ok" if not found else "DIFFERENT: " + "; ".join(found)
        lines.append(f"{v['display_name']:<26} {v['tier']:<13} rank {rank:<3} late {late:<5} {verdict}")
    band = re.split(r'<div class="?v-kpis"?>', team_view, maxsplit=1)[-1].split("</section>", 1)[0]   # the attribute may be unquoted
    for k in verdicts["team"]["kpis"]:
        tile = _between(band, f'data-tone="{k["tone"]}" data-kpi="{k["key"]}">', "</span>")
        value = _text(tile)
        expected = f"{_pct(float(k['value']))}%" if k["key"] in ("late_rate", "short_runway_share") else str(k["value"])
        if value != expected:
            problems.append(f"KPI {k['key']}: {value!r} != {expected!r} (tone {k['tone']})")
    rail = _between(team_view, '<aside class="v-rail"', "</aside>")
    if re.findall(r'data-decision-id="([^"]+)"', rail) != [d["id"] for d in verdicts["decisions"]]:
        problems.append("the rail's decisions differ from verdicts.json decisions")
    return lines, problems


def main(argv: list[str] | None = None) -> int:
    site = Path((sys.argv[1:] if argv is None else argv)[0])
    verdicts = json.loads((site / "verdicts.json").read_text(encoding="utf-8"))
    lines, problems = verify((site / "en" / "dashboard.html").read_text(encoding="utf-8"), verdicts)
    print(f"Snapshot {verdicts['source']['retrieved_at']}: {len(verdicts['editors'])} Editors, {len(verdicts['team']['kpis'])} KPIs, "
          f"{len(verdicts['decisions'])} overview decisions")
    print("\n".join(lines))
    for problem in problems:
        print(f"DIFFERENT: {problem}")
    print("numbers match the snapshot" if not problems else f"{len(problems)} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
