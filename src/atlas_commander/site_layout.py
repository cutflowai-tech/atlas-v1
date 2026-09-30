"""The file layout of a generated Atlas site: one analytical dataset, two presentation languages.

    index.html                     root entry: sends visitors to en/dashboard.html (English is the default)
    publication.json               shared release/snapshot identity for every public route (contract 1.5.0+ only)
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

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from atlas_commander.capabilities import capabilities
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


INTELLIGENCE_JSON = "intelligence-v2.json"


def optional_files(contract_version: str) -> list[str]:
    """Files a complete site may contain but never needs (Intelligence V2, contract 1.5.0+, feature-gated).

    An optional file is validated whenever it is present and is never required, so builds with and without it both validate,
    publish and roll back."""
    return [INTELLIGENCE_JSON] if capabilities(contract_version).editor_intelligence else []


def required_files(editor_ids: Iterable[str], contract_version: str) -> list[str]:
    """Exactly the files a complete site built under ``contract_version`` contains.

    ``publication.json`` exists only for contracts with publication identity (1.5.0+). Builds made under earlier contracts,
    including every build published before contract 1.5 code shipped, never had it and remain complete without it."""
    editors = list(editor_ids)
    publication = [PUBLICATION_JSON] if capabilities(contract_version).publication_identity else []
    return [ROOT_ENTRY, *publication, DASHBOARD_JSON, *(profile_json(editor) for editor in editors), *html_files(editors)]


def _json(path: Path | None) -> Any:
    try:
        return json.loads(path.read_bytes()) if path is not None else None
    except (OSError, ValueError):
        return None


def publication_problems(files: Mapping[str, Path], editor_ids: Iterable[str], contract_version: str, retrieved_at: Any) -> list[str]:
    """Release / source-snapshot identity checks shared by staged-build validation and publication.

    Under a contract with publication identity, ``publication.json`` must name this build's contract and source snapshot, the
    root, /en and /ar routes must resolve to one release and snapshot, every page must carry that identity, and the dashboard
    and every Editor Profile must embed the same publication document. Earlier contracts have no publication identity, so
    nothing is required of them (their other checks are unchanged)."""
    if not capabilities(contract_version).publication_identity:
        return []
    editors = list(editor_ids)
    publication = _json(files.get(PUBLICATION_JSON))
    if not isinstance(publication, dict):
        return [f"{PUBLICATION_JSON} is missing or invalid"]
    problems: list[str] = []
    release_id, snapshot_id = publication.get("release_id"), publication.get("snapshot_id")
    routes_value = publication.get("routes")
    routes: dict[str, Any] = routes_value if isinstance(routes_value, dict) else {}
    rows = [row if isinstance(row, dict) else {} for row in routes.values()]
    route_release_ids = {row.get("release_id") for row in rows}
    route_snapshot_ids = {row.get("snapshot_id") for row in rows}
    if not release_id or not snapshot_id or set(routes) != {"/", "/en", "/ar"} \
            or route_release_ids != {release_id} or route_snapshot_ids != {snapshot_id}:
        problems.append("root, /en and /ar do not identify one release and source snapshot")
    if publication.get("executable_contract_version") != contract_version or (publication.get("source") or {}).get("retrieved_at") != retrieved_at:
        problems.append(f"{PUBLICATION_JSON} does not identify this build's source snapshot and contract")
    for name in [ROOT_ENTRY, *html_files(editors)]:
        path = files.get(name)
        text = path.read_text(encoding="utf-8") if path is not None else ""
        if (f'<meta name="atlas-release-id" content="{release_id}">' not in text
                or f'<meta name="atlas-snapshot-id" content="{snapshot_id}">' not in text):
            problems.append(f"{name} does not identify publication {release_id} / snapshot {snapshot_id}")
    dashboard = _json(files.get(DASHBOARD_JSON))
    if not isinstance(dashboard, dict) or dashboard.get("publication") != publication:
        problems.append(f"{DASHBOARD_JSON} does not identify the site's publication")
    for editor in editors:
        profile = _json(files.get(profile_json(editor)))
        if not isinstance(profile, dict) or profile.get("publication") != publication:
            problems.append(f"{profile_json(editor)} does not identify the site's publication")
    return problems


def document_opening(locale: str) -> str:
    """How every page of ``locale`` must start (language and direction are structural, not styling)."""
    return f'<!doctype html><html lang="{locale}" dir="{DIRECTION[locale]}">'
