"""Components of the redesigned, judgment-first pages (redesign Phase 3; `atlas-redesign-handoff/03-TASKS.md` T3.2–T3.8).

Each component is a render function from values the verdict document (``verdicts.json``) already holds to an HTML fragment in one
locale. Nothing here decides anything: tiers, ranks, confidence and sentences come from the verdict engine, and a colour is chosen
from the value it shows. Styles are the ``.v-`` rules of ``web/style.py`` on the ``--v-`` tokens (T3.1), with logical properties so
both directions share one design. Every Latin value, number and ID is isolated for Arabic (T1.4).
"""

from __future__ import annotations

import hashlib
from html import escape

from atlas_commander.i18n import Html, Loc

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
