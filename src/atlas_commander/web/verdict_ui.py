"""Components of the redesigned, judgment-first pages (redesign Phase 3; `atlas-redesign-handoff/03-TASKS.md` T3.2–T3.8).

Each component is a render function from values the verdict document (``verdicts.json``) already holds to an HTML fragment in one
locale. Nothing here decides anything: tiers, ranks, confidence and sentences come from the verdict engine, and a colour is chosen
from the value it shows. Styles are the ``.v-`` rules of ``web/style.py`` on the ``--v-`` tokens (T3.1), with logical properties so
both directions share one design. Every Latin value, number and ID is isolated for Arabic (T1.4).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from typing import Any

from atlas_commander.i18n import DASH, Html, Loc
from atlas_commander.verdict.messages import KEYS, PLURAL

TONES = ("good", "warn", "bad", "neutral")
TIERS = ("best", "steady", "watch", "weakest", "low_activity")
CONFIDENCE = ("high", "medium", "low")
HORIZONS = ("today", "this_week", "ask", "management")
ROLES = ("scheduling_owner", "editors_manager", "ceo")
AVATAR_SIZES = (28, 56, 96)
ARABIC_ALEF = ("ا", "إ")   # names starting with one of these show their first two letters (handoff T3.2)


def initial(name: str) -> str:
    """The letter(s) an avatar shows without a photo: the first letter of the name, or the first two for a name starting with
    إ or ا (a lone alef is not recognisable)."""
    letters = [c for c in name.strip() if c.isalpha()]
    if not letters:
        return "?"
    if letters[0] in ARABIC_ALEF and len(letters) > 1:
        return letters[0] + letters[1]
    return letters[0].upper()


def hue(editor_id: str) -> int:
    """A stable hue for an Editor's initial avatar, derived from the Editor ID (the same colour on every build and page)."""
    return int(hashlib.sha256(editor_id.encode()).hexdigest(), 16) % 360


def avatar(editor_id: str, name: str, loc: Loc, *, size: int = 56, tier: str | None = None, rank: int | None = None,
           ranked_of: int | None = None, photo_url: str | None = None) -> Html:
    """T3.2: the photo when there is one, otherwise the initial on a colour derived from the Editor ID; a tier-coloured ring and
    the rank badge. A broken photo URL falls back to the initial (the image removes itself). The whole avatar is one image with
    an accessible name (name, tier, rank)."""
    if size not in AVATAR_SIZES:
        raise ValueError(f"avatar size {size} is not one of {AVATAR_SIZES}")
    tier_text = loc.text("ui.v.tier." + tier) if tier else None
    if rank is not None and ranked_of:
        label = loc.text("ui.v.avatar.ranked", name=name, tier=tier_text or "", rank=rank, of=ranked_of)
    elif tier_text:
        label = loc.text("ui.v.avatar.tier", name=name, tier=tier_text)
    else:
        label = name
    photo = (f'<img src="{escape(photo_url, quote=True)}" alt="" loading="lazy" decoding="async" onerror="this.remove()">'
             if photo_url else "")
    badge = f'<span class="v-av-rank" aria-hidden="true"><bdi dir="ltr">{rank}</bdi></span>' if rank is not None else ""
    tier_attr = f' data-tier="{escape(tier)}"' if tier else ""
    return Html(f'<span class="v-av s{size}" role="img" aria-label="{escape(label, quote=True)}" data-editor-id="{escape(editor_id, quote=True)}"'
                f'{tier_attr} style="--v-av-hue:{hue(editor_id)}">'
                f'<span class="v-av-i" aria-hidden="true"><bdi>{escape(initial(name))}</bdi></span>{photo}{badge}</span>')


def whole_pct(rate: float) -> int:
    """A rate as a whole percentage, halves rounded up (0.545 -> 55), as people read it."""
    return int(Decimal(str(rate * 100)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def late_bar(late_rate: float | None, team_late_rate: float | None, tone: str, loc: Loc, *, late: int | None = None,
             classifiable: int | None = None) -> Html:
    """T3.3: the Editor's late rate as a horizontal bar with a marker at the team average; the tone (``metrics.late_tone``) was
    decided by the engine. Logical properties make the bar grow from the inline start, so it mirrors in Arabic. The accessible name
    and the tooltip say the value and "Team average N%"."""
    if tone not in TONES:
        raise ValueError(f"unknown tone {tone!r}")
    if late_rate is None:
        return Html(f'<div class="v-late" data-tone="neutral"><span class="v-late-none">{loc.t("ui.v.late.none")}</span></div>')
    pct = whole_pct(late_rate)
    team = whole_pct(team_late_rate) if team_late_rate is not None else None
    team_text = loc.text("ui.v.late.team", team_pct=f"{team}%") if team is not None else ""
    if late is not None and classifiable:
        label = loc.text("ui.v.late.aria_count", late_pct=f"{pct}%", late=late, n=classifiable)
    else:
        label = loc.text("ui.v.late.aria", late_pct=f"{pct}%")
    label = f"{label} {team_text}." if team_text else label
    marker = (f'<span class="v-late-team" style="inset-inline-start:{min(max(team, 0), 100)}%" aria-hidden="true"></span>'
              if team is not None else "")
    return Html(f'<div class="v-late" data-tone="{tone}" role="img" aria-label="{escape(label, quote=True)}" title="{escape(team_text, quote=True)}">'
                f'<span class="v-late-track"><span class="v-late-fill" style="inline-size:{min(max(pct, 0), 100)}%"></span>{marker}</span>'
                f'<span class="v-late-v" aria-hidden="true">{loc.ltr(f"{pct}%")}</span></div>')


def speed_pill(delta_pct: float | None, band: str | None, tone: str, loc: Loc) -> Html:
    """T3.4: "23% faster", "43% slower" or "Same as team"; band and tone come from the engine (``metrics.speed_band``/``speed_tone``)."""
    if tone not in TONES:
        raise ValueError(f"unknown tone {tone!r}")
    if band is None or delta_pct is None:
        return Html(f'<span class="v-pill v-speed" data-tone="neutral">{loc.t("ui.v.speed.none")}</span>')
    if band == "same":
        text = loc.t("ui.v.speed.same")
    else:
        text = loc.t("ui.v.speed." + band, pct=loc.ltr(f"{abs(int(Decimal(str(delta_pct)).quantize(Decimal(1), rounding=ROUND_HALF_UP)))}%"))
    return Html(f'<span class="v-pill v-speed" data-tone="{tone}" data-band="{escape(band)}">{text}</span>')


def tier_chip(tier: str, loc: Loc) -> Html:
    """T3.4: the tier's label on its colour (always with the text, never colour alone)."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    return Html(f'<span class="v-chip v-tier" data-tier="{tier}"><span class="v-dot" aria-hidden="true"></span><span>{loc.t("ui.v.tier." + tier)}</span></span>')


def confidence_tag(confidence: str, loc: Loc, *, in_profile: bool = False) -> Html:
    """T3.4: on cards only a Low confidence shows ("Low confidence"); in a profile every level shows ("Confidence: High")."""
    if confidence not in CONFIDENCE:
        raise ValueError(f"unknown confidence {confidence!r}")
    if in_profile:
        return Html(f'<span class="v-chip v-conf" data-confidence="{confidence}">{loc.t("ui.v.confidence.level", level=loc.t("ui.v.confidence." + confidence))}</span>')
    if confidence != "low":
        return Html("")
    return Html(f'<span class="v-chip v-conf" data-confidence="low">{loc.t("ui.v.confidence.low_tag")}</span>')


def person_card(verdict: Mapping[str, Any], headline: Html, loc: Loc) -> Html:
    """T3.5: one Editor of ``verdicts.json`` as a card: avatar (tier ring, rank badge), name, the one-line verdict (``headline``,
    already rendered from its message key), late-rate bar, speed pill, projects this month and, only when it applies, "Low
    confidence". The whole card is one link to the Editor's profile route (``#/editor/<id>``, the drawer of T4.4)."""
    m = verdict["metrics"]
    editor_id = verdict["editor_id"]
    projects = loc.t("ui.v.card.this_month", n=loc.num(m["completed"]))
    if m["active"]:
        projects = Html(f'{projects}<span class="v-card-open">{loc.t("ui.v.card.in_progress", n=loc.num(m["active"]))}</span>')
    rows = [(loc.t("ui.v.card.late"), late_bar(m["late_rate"], m["team_late_rate"], m["late_tone"], loc, late=m["late_count"],
                                                classifiable=m["deadline_classifiable"])),
            (loc.t("ui.v.card.speed"), speed_pill(m["speed_delta_pct"], m["speed_band"], m["speed_tone"], loc)),
            (loc.t("ui.v.card.projects"), projects)]
    body = "".join(f'<span class="v-card-k">{k}</span><span class="v-card-v">{v}</span>' for k, v in rows)
    tag = confidence_tag(verdict["confidence"], loc)
    return Html(f'<a class="v-card" href="#/editor/{escape(editor_id, quote=True)}" data-editor-id="{escape(editor_id, quote=True)}" '
                f'data-tier="{escape(verdict["tier"])}">'
                f'<span class="v-card-h">{avatar(editor_id, verdict["display_name"], loc, size=56, tier=verdict["tier"], rank=verdict["rank"], ranked_of=verdict["ranked_of"], photo_url=verdict.get("photo_url"))}'
                f'<span class="v-card-name">{loc.src(verdict["display_name"])}</span></span>'
                f'<span class="v-card-verdict">{headline}</span>'
                f'<span class="v-card-m">{body}</span>'
                f'{f"<span class=v-card-f>{tag}</span>" if tag else ""}</a>')


def decision_card(decision: Mapping[str, Any], title: Html, editors: Mapping[str, Mapping[str, Any]], loc: Loc) -> Html:
    """T3.6: one decision of ``verdicts.json``: the horizon label on its colour stripe, the title (rendered by the caller from its key)
    and the owners: each owning Editor's avatar opens their profile (``#/editor/<id>``), then their names; a role owner is named by
    its role. ``editors`` maps Editor IDs to their verdicts (name, tier, rank)."""
    horizon = decision["horizon"]
    if horizon not in HORIZONS:
        raise ValueError(f"unknown horizon {horizon!r}")
    owners = [editors[i] for i in decision["owner_editor_ids"] if i in editors]
    faces = "".join(f'<a class="v-dec-face" href="#/editor/{escape(v["editor_id"], quote=True)}">'
                    f'{avatar(v["editor_id"], v["display_name"], loc, size=28, tier=v["tier"], photo_url=v.get("photo_url"))}</a>' for v in owners)
    parts = []
    if owners:
        parts.append(loc.comma().join(str(loc.src(v["display_name"])) for v in owners))
    if decision.get("owner_role"):
        role = decision["owner_role"]
        if role not in ROLES:
            raise ValueError(f"unknown owner role {role!r}")
        parts.append(str(loc.t("ui.v.decision.owner", role=loc.t("ui.v.role." + role))))
    who = " · ".join(parts)
    return Html(f'<article class="v-dec" data-horizon="{horizon}" data-decision-id="{escape(decision["id"], quote=True)}">'
                f'<p class="v-dec-when">{loc.t("ui.v.horizon." + horizon)}</p><h3 class="v-dec-title">{title}</h3>'
                f'<p class="v-dec-who">{f"<span class=v-dec-faces>{faces}</span>" if faces else ""}<span>{who}</span></p></article>')


def tier_section(tier: str, cards: list[Html], loc: Loc) -> Html:
    """T3.7: a tier's heading (colour square, label, count, short description) above a responsive grid of person cards: as many
    270 px columns as fit, at most four, and a lone card keeps its column width (no orphan stretching). No cards, no section."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    if not cards:
        return Html("")
    heading = f"v-tier-{tier}-h"
    return Html(f'<section class="v-tsec" data-tier="{tier}" aria-labelledby="{heading}">'
                f'<header class="v-tsec-h"><h2 id="{heading}"><span class="v-sq" aria-hidden="true"></span>{loc.t("ui.v.tier." + tier)}'
                f'<span class="v-tsec-n">{loc.num(len(cards))}</span></h2><p>{loc.t("ui.v.tier_desc." + tier)}</p></header>'
                f'<div class="v-grid">{"".join(cards)}</div></section>')

PERCENT_KPIS = ("late_rate", "short_runway_share")   # KPI values that are percentages; the others are counts


def kpi_value(key: str, value: str, loc: Loc) -> Html:
    """A KPI value from ``team.kpis[].value`` (a language-neutral numeral) as people read it: a whole percentage, or a count."""
    if not value:
        return Html("—")
    if key in PERCENT_KPIS:
        return loc.ltr(f"{whole_pct(float(value) / 100)}%")
    return loc.num(value)


def verdict_band(headline: Html, supporting: Html, kpis: list[tuple[Mapping[str, Any], Html]], loc: Loc) -> Html:
    """T3.8: the eyebrow "This month's verdict", the team headline and supporting sentence (rendered by the caller from their keys),
    and up to three KPI tiles (``team.kpis`` with their rendered labels; the tone was decided by the engine). Side by side on wide
    containers, stacked on narrow ones (a container query, so the band follows its own width), the tiles staying in one row."""
    tiles = "".join(f'<div class="v-kpi" data-tone="{escape(k["tone"])}" data-kpi="{escape(k["key"])}"><span class="v-kpi-v">{kpi_value(k["key"], k["value"], loc)}</span>'
                    f'<span class="v-kpi-l">{label}</span></div>' for k, label in kpis[:3])
    return Html(f'<section class="v-band" aria-labelledby="v-band-h"><div class="v-band-in"><div class="v-band-t"><p class="v-eyebrow">{loc.t("ui.v.band.eyebrow")}</p>'
                f'<h1 id="v-band-h">{headline}</h1><p class="v-band-s">{supporting}</p></div>'
                f'{f"<div class=v-kpis>{tiles}</div>" if tiles else ""}</div></section>')


def _number(value: Any) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def _param(name: str, value: Any, loc: Loc) -> Html:
    """One ``Msg`` parameter as people read it, by the unit its name carries (schema ``Msg``)."""
    if value is None or value == "":
        return Html(DASH)
    if name.endswith("_pct"):
        whole = int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return loc.ltr(f"{'−' if whole < 0 else ''}{abs(whole)}%")
    if name.endswith("_hours"):
        return loc.t("unit.hours", value=loc.ltr(f"{float(value):.1f}"))
    if name == "names":
        return Html(loc.comma().join(loc.src(v) for v in value))
    if name == "labels":
        return loc.labels(list(value))
    if name in ("name", "video_type", "status"):
        return loc.src(value)
    if name == "item_id":
        return loc.ltr(str(value))
    if name == "dimension":
        return loc.t("ui.v.dimension." + str(value))
    return loc.num(_number(value))


def message(msg: Mapping[str, Any], loc: Loc) -> Html:
    """A ``Msg`` from ``verdicts.json`` in ``loc`` (T4.1): the catalogue template of its key with every parameter formatted by its
    unit. A parameter the key may carry but this message omits (e.g. an unknown Video Type) reads as a dash."""
    key, params = msg["key"], msg.get("params") or {}
    allowed = KEYS.get(key)
    if allowed is None:
        raise KeyError(f"verdict message {key!r} is not in the registry (atlas_commander.verdict.messages)")
    unknown = set(params) - set(allowed)
    if unknown:
        raise KeyError(f"verdict message {key!r} has parameters {sorted(unknown)} the registry does not list")
    values = {name: _param(name, params.get(name), loc) for name in allowed if name != "count"}
    if key in PLURAL:
        return loc.counted(key, int(params["count"]), **values)
    return loc.t(key, **values)
