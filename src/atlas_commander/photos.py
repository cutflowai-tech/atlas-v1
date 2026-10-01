"""Editor photos for the redesigned pages (redesign T5.1, T5.2).

Monday cannot supply them: Editors are values of the board's "Editor Name" dropdown on a shared account, not Monday users, so there is
no user avatar to read (docs/redesign/DECISIONS.md T0.3, R22). An admin adds a photo as a file named after the Editor ID,
``<photo dir>/<editor-id>.jpg`` (or ``.jpeg``, ``.png``, ``.webp``). The photo directory is, in order: the directory named by
``ATLAS_EDITOR_PHOTOS``; ``$ATLAS_DATA_DIR/editor-photos`` (in production the persistent data directory the host bind-mounts, so no
image rebuild is needed); otherwise ``assets/editors/`` in the repository (local builds). Steps: docs/redesign/MAP.md, "Editor photos".
The site build embeds each valid photo in the pages as a ``data:`` URI, because the pages make no network request and nginx serves only
the language trees. A file that is not an image of those types, or is
larger than ``MAX_BYTES``, is skipped (the Editor keeps the initial) and reported by :func:`check`.
"""

from __future__ import annotations

import base64
import os
import sys
from collections.abc import Iterable
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "assets" / "editors"
ENV = "ATLAS_EDITOR_PHOTOS"
DATA_ENV, DATA_SUBDIR = "ATLAS_DATA_DIR", "editor-photos"
EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
MAX_BYTES = 150 * 1024   # a 192 x 192 photo (twice the largest avatar) is far below this
SIGNATURES = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",)}


def photo_dir() -> Path:
    if os.environ.get(ENV):
        return Path(os.environ[ENV])
    if os.environ.get(DATA_ENV):
        return Path(os.environ[DATA_ENV]) / DATA_SUBDIR
    return DEFAULT_DIR


def _media_type(data: bytes) -> str | None:
    for media_type, signatures in SIGNATURES.items():
        if any(data.startswith(signature) for signature in signatures):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _file(editor_id: str, directory: Path) -> Path | None:
    return next((directory / f"{editor_id}{ext}" for ext in EXTENSIONS if (directory / f"{editor_id}{ext}").is_file()), None)


def check(editor_ids: Iterable[str], directory: Path | None = None) -> tuple[dict[str, Path], list[str]]:
    """The usable photo file of each Editor that has one, and why any other photo file is not used."""
    directory = directory or photo_dir()
    usable: dict[str, Path] = {}
    problems: list[str] = []
    for editor_id in editor_ids:
        path = _file(editor_id, directory)
        if path is None:
            continue
        data = path.read_bytes()
        if len(data) > MAX_BYTES:
            problems.append(f"{path.name}: {len(data)} bytes, more than {MAX_BYTES}; resize it (192 x 192 px is enough)")
        elif _media_type(data) is None:
            problems.append(f"{path.name}: not a JPEG, PNG or WebP image")
        else:
            usable[editor_id] = path
    return usable, problems


def editor_photos(editor_ids: Iterable[str], directory: Path | None = None) -> dict[str, str]:
    """``data:`` URIs of the usable photos, by Editor ID (Editors without one are absent and keep their initial)."""
    usable, _ = check(editor_ids, directory)
    out = {}
    for editor_id, path in usable.items():
        data = path.read_bytes()
        out[editor_id] = f"data:{_media_type(data)};base64,{base64.b64encode(data).decode('ascii')}"
    return out


def main(argv: list[str] | None = None) -> int:
    """``python3 -m atlas_commander.photos <dashboard.json>``: which Editors have a usable photo, and why a file is refused."""
    import json

    args = sys.argv[1:] if argv is None else argv
    editors = json.loads(Path(args[0]).read_text(encoding="utf-8"))["editors"]
    usable, problems = check([e["editor_id"] for e in editors])
    print(f"photo directory: {photo_dir()}")
    for e in editors:
        print(f"  {e['editor_id']:<20} {e['display_name']:<28} {usable[e['editor_id']].name if e['editor_id'] in usable else '— (initial)'}")
    for problem in problems:
        print(f"  refused: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
