"""Screenshot a built Atlas page in headless Chrome (redesign evidence; development only).

    PYTHONPATH=tests python3 scripts/redesign_screenshot.py out/real/ar/dashboard.html shot.png \
        [--fragment /system] [--width 390] [--height 844] [--light] [--full] [--selector CSS] [--before JS]

``--before`` runs a JavaScript function body (async, with ``wait(ms)``) before the capture, e.g. to open a drawer.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from browser_harness import Browser


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("page", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--fragment", default="")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--light", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--selector", default=None)
    parser.add_argument("--before", default="")
    args = parser.parse_args()
    with Browser(width=args.width, height=args.height, dark=not args.light, mobile=args.width < 768) as browser:
        browser.open(args.page.read_text(encoding="utf-8"), args.fragment)
        browser.run("await wait(300);" + args.before + "; await wait(300); return null;")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        browser.screenshot(args.out, selector=args.selector, full_page=args.full)


if __name__ == "__main__":
    main()
