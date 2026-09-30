"""Automated accessibility audit of a built page in headless Chrome (redesign T6.2), without a new dependency.

``audit(page, route, dark)`` returns the serious issues found: the in-page checks of ``js/a11y_check.js`` (contrast, focusable content
under aria-hidden, ARIA references, image alternatives, language, one h1) plus the accessible names Chrome itself computes
(``Accessibility.getFullAXTree``): every link, button, image, dialog, tab and form control must have one. ``reduced_motion(page)``
returns the redesigned elements that still animate when the reader asks for reduced motion.

    PYTHONPATH=src:tests python3 tests/a11y.py out/real      # audit a build: every route, both languages, both themes
"""

from __future__ import annotations

import sys
from pathlib import Path

from browser_harness import Browser

CHECK = (Path(__file__).resolve().parent / "js" / "a11y_check.js").read_text(encoding="utf-8")
NAMED_ROLES = {"link", "button", "image", "img", "dialog", "tab", "checkbox", "textbox", "searchbox", "combobox", "menuitem", "switch"}
MOTION = ".v-card, .v-profile, .v-scrim"


def _names(browser: Browser) -> list[str]:
    browser.call("Accessibility.enable")
    issues = []
    for node in browser.call("Accessibility.getFullAXTree")["nodes"]:
        if node.get("ignored"):
            continue
        role = (node.get("role") or {}).get("value", "")
        name = str((node.get("name") or {}).get("value", "")).strip()
        if role in NAMED_ROLES and not name:
            issues.append(f"{role} without an accessible name (backend node {node.get('backendDOMNodeId')})")
    return issues


def audit(page: str, route: str = "", *, dark: bool = True, width: int = 1280, height: int = 900) -> list[str]:
    with Browser(width=width, height=height, dark=dark, mobile=width < 768) as browser:
        browser.open(page, route)
        issues = list(browser.run(CHECK))
        return issues + _names(browser)


def reduced_motion(page: str, route: str = "") -> list[str]:
    with Browser(width=1280, height=900) as browser:
        browser.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        browser.open(page, route)
        return list(browser.run(f"""
            await wait(200);
            return [...document.querySelectorAll({MOTION!r})].filter(el => {{
                const cs = getComputedStyle(el); return cs.transitionDuration.split(',').some(d => parseFloat(d) > 0) || cs.animationName !== 'none';
            }}).map(el => el.className);
        """))


def main(site: str) -> int:
    failures = 0
    for locale in ("en", "ar"):
        page = (Path(site) / locale / "dashboard.html").read_text(encoding="utf-8")
        editor = page.split('<template id="vp-', 1)[1].split('"', 1)[0] if '<template id="vp-' in page else ""
        for route in ("", f"/editor/{editor}" if editor else "", f"/profile/{editor}" if editor else "", "/system"):
            for dark in (True, False):
                issues = audit(page, route, dark=dark)
                failures += len(issues)
                print(f"{locale} {route or '/':<24} {'dark ' if dark else 'light'} {len(issues)} serious issue(s)")
                for issue in issues[:10]:
                    print(f"    {issue}")
        motion = reduced_motion(page)
        failures += len(motion)
        print(f"{locale} reduced motion: {'ok' if not motion else motion}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
