"""Atlas presentation localization: English (LTR) and Arabic (RTL). Presentation only.

Every Atlas-owned user-facing string in the HTML renderers comes from one versioned catalogue,
``atlas_commander/locales/catalog.json``, through :class:`Loc`. Both languages render the same
view model; nothing here computes, reclassifies or rounds a metric differently per language.

Rules enforced here:

- A key missing from the catalogue, or a production locale missing a text, raises
  :class:`TranslationError`. There is no silent fallback to English.
- Parameters are HTML-escaped unless they are :class:`Html` fragments built by this module
  (source values, numbers, counts), so catalogue text can never inject markup.
- Monday-derived values (names, labels, Video Types, statuses) are rendered unchanged inside
  ``<bdi>`` so they keep their own direction in RTL pages; technical identifiers use
  ``<code dir="ltr">`` (:meth:`Loc.tech`). Numbers, including every count shown as words, are wrapped in
  ``<data value>`` so English and Arabic can be checked for identical values.
- Digits are Western (0-9) in both languages; dates stay Gregorian and UTC.

``python3 -m atlas_commander.i18n review`` prints the Arabic translation review table.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("locales") / "catalog.json"
CATALOG_VERSION = "atlas-i18n-v1"
LOCALES = ("en", "ar")
DIRECTION = {"en": "ltr", "ar": "rtl"}
REVIEW_STATUSES = ("Approved from brief", "Implemented conservatively", "Needs Arabic Review")
PLURAL_FORMS = {"en": ("one", "other"), "ar": ("zero", "one", "two", "few", "many", "other")}
# Optional grammatical variant: the Arabic dual after a preposition (genitive), e.g. "في مشروعين".
CASE_FORMS = {"gen": {"two": "two_gen"}}
MONTHS = {
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"),
    "ar": ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"),
}
MONTHS_SHORT = {"en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), "ar": MONTHS["ar"]}
DASH = "—"


# A run of Latin words inside Arabic text ("Requested ETA", "Video Type", "D53"); entities and {placeholders} are skipped.
_LATIN = re.compile(r"(&#?\w+;)|(\{[^{}]*\})|([A-Za-z][A-Za-z0-9]*(?:[ ./\-][A-Za-z0-9]+)*)")


def isolate_latin(text: str) -> str:
    """Wrap every run of Latin words in escaped, tag-free text in ``<bdi dir="ltr">`` (redesign T1.4, ATLAS-RTL-002)."""
    return _LATIN.sub(lambda m: f'<bdi dir="ltr">{m.group(3)}</bdi>' if m.group(3) else m.group(0), text)


class TranslationError(KeyError):
    """A key or locale text is missing, or the catalogue is malformed. Localized builds fail on it."""


class Html(str):
    """An HTML fragment produced by this module (safe to insert without escaping)."""


def _safe(value: Any) -> str:
    return value if isinstance(value, Html) else escape(str(value))


def _check_entry(key: str, entry: Any) -> list[str]:
    problems = []
    if not isinstance(entry, dict):
        return [f"{key}: entry is not an object"]
    if entry.get("status") not in REVIEW_STATUSES:
        problems.append(f"{key}: status must be one of {REVIEW_STATUSES}")
    if not entry.get("context"):
        problems.append(f"{key}: context is required")
    for locale in LOCALES:
        text = entry.get(locale)
        if isinstance(text, dict):
            forms = set(PLURAL_FORMS[locale])
            missing = forms - set(text)
            extra = set(text) - forms - {"two_gen"}
            if missing or extra or not all(isinstance(v, str) and v for v in text.values()):
                problems.append(f"{key}: {locale} plural forms must be exactly {sorted(forms)} (plus optional two_gen), all non-empty")
        elif not isinstance(text, str) or not text:
            problems.append(f"{key}: missing {locale} text")
    return problems


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict[str, Any]]:
    """The validated catalogue. Raises TranslationError if any entry lacks a production locale."""
    document = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if document.get("catalog_version") != CATALOG_VERSION or tuple(document.get("locales") or ()) != LOCALES:
        raise TranslationError(f"catalogue must be {CATALOG_VERSION} with locales {LOCALES}")
    entries = document.get("entries")
    if not isinstance(entries, dict) or not entries:
        raise TranslationError("catalogue has no entries")
    problems = [problem for key, entry in entries.items() for problem in _check_entry(key, entry)]
    if problems:
        raise TranslationError("invalid catalogue:\n- " + "\n- ".join(problems))
    return entries


def plural_category(locale: str, n: int) -> str:
    """CLDR plural category for a whole number (English and Arabic rules)."""
    if locale == "en":
        return "one" if n == 1 else "other"
    rem = n % 100
    if n == 0:
        return "zero"
    if n == 1:
        return "one"
    if n == 2:
        return "two"
    if 3 <= rem <= 10:
        return "few"
    if 11 <= rem <= 99:
        return "many"
    return "other"


def _month_parts(value: str) -> tuple[int, int]:
    year, month = str(value)[:7].split("-")
    return int(year), int(month)


class Loc:
    """Presentation helpers for one locale."""

    def __init__(self, code: str, isolate: bool = False) -> None:
        if code not in LOCALES:
            raise TranslationError(f"unsupported locale {code!r}; production locales are {LOCALES}")
        self.code, self.dir = code, DIRECTION[code]
        # Bidi isolation of Latin terms and dates in right-to-left text. Only the contract 1.5 app turns it on, so the
        # contract 1.3/1.4 pages stay byte for byte (fixtures/golden).
        self.isolate = isolate and DIRECTION[code] == "rtl"

    def isolating(self) -> Loc:
        """The same locale with bidi isolation of Latin terms and dates (a no-op for left-to-right locales)."""
        return Loc(self.code, isolate=True)

    def _text_html(self, template: str) -> str:
        text = escape(template, quote=False)
        return isolate_latin(text) if self.isolate else text

    def __repr__(self) -> str:
        return f"Loc({self.code!r})"

    def other(self) -> Loc:
        return Loc("ar" if self.code == "en" else "en", self.isolate)

    # ------------------------------------------------------------------ catalogue text
    @staticmethod
    def has(key: str) -> bool:
        """Whether the catalogue defines ``key`` (used only to show an unknown technical code as the raw code)."""
        return key in catalog()

    def _raw(self, key: str) -> Any:
        try:
            entry = catalog()[key]
        except KeyError:
            raise TranslationError(f"unknown translation key {key!r}") from None
        return entry[self.code]

    def _form(self, key: str, n: int, case: str | None) -> str:
        forms = self._raw(key)
        if not isinstance(forms, dict):
            raise TranslationError(f"{key!r} is not a plural entry")
        category = plural_category(self.code, n)
        variant = CASE_FORMS.get(case or "", {}).get(category)
        return str(forms.get(variant, forms[category]) if variant else forms[category])

    def text(self, key: str, **params: Any) -> str:
        """Plain text (for attributes such as aria-label and title); the caller escapes it."""
        raw = self._raw(key)
        if not isinstance(raw, str):
            raise TranslationError(f"{key!r} is a plural entry; use count()")
        return raw.format(**{k: str(v) for k, v in params.items()})

    def t(self, key: str, **params: Any) -> Html:
        """HTML: the catalogue text escaped, with escaped (or already-safe) parameters."""
        raw = self._raw(key)
        if not isinstance(raw, str):
            raise TranslationError(f"{key!r} is a plural entry; use count()")
        return Html(self._text_html(raw).format(**{k: _safe(v) for k, v in params.items()}))

    def count(self, key: str, n: int, case: str | None = None, **params: Any) -> Html:
        """A counted phrase ("5 projects", "مشروعان"); the value stays machine-readable in <data value>."""
        text = self._text_html(self._form(key, n, case)).format(n=n, **{k: _safe(v) for k, v in params.items()})
        return Html(f'<data value="{int(n)}">{text}</data>')

    def count_text(self, key: str, n: int, case: str | None = None, **params: Any) -> str:
        return self._form(key, n, case).format(n=n, **{k: str(v) for k, v in params.items()})

    def plural(self, key: str, n: int, case: str | None = None) -> Html:
        """Plural-agreeing words without the number (the number is shown separately)."""
        return Html(self._text_html(self._form(key, n, case)).format(n=n))

    # ------------------------------------------------------------------ values
    @staticmethod
    def num(value: Any) -> Html:
        if value is None:
            return Html(DASH)
        return Html(f'<data value="{escape(str(value))}">{escape(str(value))}</data>')

    @staticmethod
    def src(value: Any) -> Html:
        """A Monday-derived value shown exactly as recorded, direction-isolated."""
        return Html(f"<bdi>{escape(str(value))}</bdi>")

    @staticmethod
    def tech(value: Any) -> Html:
        """A technical identifier: always left-to-right."""
        return Html(f'<code dir="ltr">{escape(str(value))}</code>')

    @staticmethod
    def ltr(text: str) -> Html:
        return Html(f'<bdi dir="ltr">{escape(text)}</bdi>')

    def labels(self, labels: list[str], fallback: str = DASH) -> Html:
        """Video Type labels (Monday values), each isolated, joined with a neutral " + "."""
        return Html(" + ".join(self.src(label) for label in labels)) if labels else Html(escape(fallback))

    def hours(self, seconds: Any, signed: bool = False) -> Html:
        """Hours with one decimal ("10.0h" / "10.0 ساعة"); the number itself is identical in both languages."""
        if seconds is None:
            return Html(DASH)
        value = f"{seconds / 3600:+.1f}" if signed else f"{seconds / 3600:.1f}"
        return self.t("unit.hours", value=self.ltr(value))

    def hours_text(self, seconds: Any, signed: bool = False) -> str:
        if seconds is None:
            return DASH
        return self.text("unit.hours", value=f"{seconds / 3600:+.1f}" if signed else f"{seconds / 3600:.1f}")

    def pct(self, rate: Any) -> Html:
        return Html(DASH) if rate is None else self.ltr(f"{rate * 100:.1f}%")

    def pct_value(self, value: Any, signed: bool = False) -> Html:
        """A value already in percent (e.g. editor_vs_team_median_pct)."""
        if value is None:
            return Html(DASH)
        return self.ltr(f"{value:+.1f}%" if signed else f"{value:.1f}%")

    def month(self, value: str | None) -> str:
        """``2026-09`` -> ``September 2026`` / ``سبتمبر 2026``."""
        if not value:
            return DASH
        year, month = _month_parts(value)
        return f"{MONTHS[self.code][month - 1]} {year}"

    def month_short(self, value: str) -> str:
        return MONTHS_SHORT[self.code][_month_parts(value)[1] - 1]

    def date(self, value: Any, with_time: bool = True) -> str:
        """Same instant and UTC in both languages: ``28 Sep 2026, 14:05 UTC`` / ``28 سبتمبر 2026، 14:05 UTC``."""
        if not value:
            return DASH
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        day = f"{moment.day:02d} {MONTHS_SHORT[self.code][moment.month - 1]} {moment.year}"
        if not with_time:
            return day
        return f"{day}{'، ' if self.code == 'ar' else ', '}{moment:%H:%M} UTC"

    def when(self, value: Any, with_time: bool = True) -> Html:
        """A formatted date as HTML: :meth:`date`, isolated in right-to-left text so it never reorders with its neighbours.

        The isolate is ``<time datetime>`` (isolated by the stylesheet) in the locale's own direction, because an Arabic date is
        written with an Arabic month name."""
        text = escape(self.date(value, with_time))
        if not (self.isolate and value):
            return Html(text)
        return Html(f'<time datetime="{escape(str(value))}">{text}</time>')

    def comma(self) -> str:
        return "، " if self.code == "ar" else ", "


EN, AR = Loc("en"), Loc("ar")


def locales() -> list[Loc]:
    return [Loc(code) for code in LOCALES]


def review_markdown() -> str:
    """The human review table for every Atlas-owned Arabic string (no raw Monday values are in the catalogue)."""
    entries = catalog()

    def cell(value: Any) -> str:
        if isinstance(value, dict):
            value = " / ".join(f"{form}: {text}" for form, text in value.items())
        return str(value).replace("|", "\\|").replace("\n", " ")

    counts = {status: sum(1 for e in entries.values() if e["status"] == status) for status in REVIEW_STATUSES}
    lines = [
        "# Atlas Arabic translation review",
        "",
        f"Generated from `src/atlas_commander/locales/catalog.json` ({CATALOG_VERSION}) by `python3 -m atlas_commander.i18n review`.",
        "Do not edit by hand. Raw Monday values (Editor names, Video Types, statuses, labels, IDs) are never translated and are not listed.",
        "",
        f"{len(entries)} keys: " + ", ".join(f"{n} {status}" for status, n in counts.items()) + ".",
        "",
        "| Key | English | Arabic | Context | Status | Notes |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| `{key}` | {cell(e['en'])} | {cell(e['ar'])} | {cell(e['context'])} | {e['status']} | {cell(e.get('notes', ''))} |"
              for key, e in sorted(entries.items(), key=lambda pair: (REVIEW_STATUSES.index(pair[1]["status"]) * -1, pair[0]))]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if sys.argv[1:] != ["review"]:
        print("usage: python3 -m atlas_commander.i18n review", file=sys.stderr)
        raise SystemExit(2)
    sys.stdout.write(review_markdown())
