"""The file layout of a generated Atlas site: one analytical dataset, two presentation languages.

    index.html                     root entry: sends visitors to en/dashboard.html (English is the default)
    publication.json               shared release/snapshot identity for every public route
    dashboard.json                 language-neutral CEO Dashboard document
    profiles/<editor_id>.json      language-neutral Editor Profiles (the analytical source of every page)
    en/index.html, ar/index.html   /en/ and /ar/ entries, each sending visitors to that language's dashboard
    en/dashboard.html              CEO Dashboard (and in-page Editor Profiles), English, LTR
    ar/dashboard.html              the same, Arabic, RTL
    en/profiles/<editor_id>.html   full Editor Profile report, English
    ar/profiles/<editor_id>.html   the same, Arabic

A build is complete only when every one of these files exists for every Editor; both languages are
produced, validated, published and rolled back together. Used by the build (``profile_cli``), the
staged-build validation (``atlas_sync.run``) and publication (``atlas_sync.publish``).
"""

from __future__ import annotations

from collections.abc import Iterable

from atlas_commander.i18n import DIRECTION, LOCALES

ROOT_ENTRY = "index.html"
PUBLICATION_JSON = "publication.json"
DASHBOARD_JSON = "dashboard.json"
DEFAULT_LOCALE = "en"
# The page whose hash is re-checked through the live pointer after a publication.
PUBLISHED_CHECK = f"{DEFAULT_LOCALE}/dashboard.html"


def profile_json(editor_id: str) -> str:
    return f"profiles/{editor_id}.json"


def locale_index(locale: str) -> str:
    return f"{locale}/index.html"


def dashboard_html(locale: str) -> str:
    return f"{locale}/dashboard.html"


def profile_html(locale: str, editor_id: str) -> str:
    return f"{locale}/profiles/{editor_id}.html"


def html_files(editor_ids: Iterable[str]) -> dict[str, str]:
    """Every localized HTML page mapped to its locale."""
    editors = list(editor_ids)
    pages = {}
    for locale in LOCALES:
        pages[locale_index(locale)] = locale
        pages[dashboard_html(locale)] = locale
        pages.update({profile_html(locale, editor): locale for editor in editors})
    return pages


def required_files(editor_ids: Iterable[str]) -> list[str]:
    """Exactly the files a complete site contains."""
    editors = list(editor_ids)
    return [ROOT_ENTRY, PUBLICATION_JSON, DASHBOARD_JSON, *(profile_json(editor) for editor in editors), *html_files(editors)]


def document_opening(locale: str) -> str:
    """How every page of ``locale`` must start (language and direction are structural, not styling)."""
    return f'<!doctype html><html lang="{locale}" dir="{DIRECTION[locale]}">'
