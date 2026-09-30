"""Redesign T5.1: Editor photos from admin-added files, shown in the person card and the profile drawer; without one, the initial."""

import base64
import json
import os
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from browser_harness import chrome, run_scenario
from redesign_site import CONTRACT, document

from atlas_commander import photos, profile_cli, site_layout
from atlas_commander.dashboard_html import render_dashboard_html
from atlas_commander.demo import GENERATED_AT, showcase_extract
from atlas_commander.i18n import AR, EN
from atlas_commander.verdict.site import VERDICTS_JSON


def png(width: int = 8, height: int = 8, rgb: tuple[int, int, int] = (60, 120, 200)) -> bytes:
    """A valid PNG without an image library (8-bit RGB, one colour)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class PhotoFilesTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="atlas-photos-"))
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_usable_refused_and_missing_photos(self):
        (self.dir / "e1.png").write_bytes(png())
        (self.dir / "e2.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)
        (self.dir / "e3.jpg").write_bytes(b"not an image")
        (self.dir / "e4.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * (photos.MAX_BYTES + 1))
        usable, problems = photos.check(["e1", "e2", "e3", "e4", "e5"], self.dir)
        self.assertEqual(sorted(usable), ["e1", "e2"])
        self.assertEqual(len(problems), 2)
        uris = photos.editor_photos(["e1", "e5"], self.dir)
        self.assertEqual(list(uris), ["e1"])
        self.assertTrue(uris["e1"].startswith("data:image/png;base64,iVBORw0KGgo"))

    def test_the_directory_can_be_set_by_the_environment(self):
        (self.dir / "e1.png").write_bytes(png())
        with mock.patch.dict(os.environ, {photos.ENV: str(self.dir)}):
            self.assertEqual(photos.photo_dir(), self.dir)
            self.assertEqual(list(photos.editor_photos(["e1"])), ["e1"])
        with mock.patch.dict(os.environ, {photos.ENV: ""}):
            self.assertEqual(photos.photo_dir(), photos.DEFAULT_DIR)


def rendered(loc=EN, with_photo=True):
    verdicts = document(VERDICTS_JSON)
    editor = verdicts["editors"][0]["editor_id"]
    uri = "data:image/png;base64," + base64.b64encode(png()).decode()
    html = render_dashboard_html(document(site_layout.DASHBOARD_JSON), {}, None, loc, intelligence=document("intelligence-v2.json"),
                                 verdicts=verdicts, photos={editor: uri} if with_photo else None)
    return html, editor, uri


class PhotoRenderTests(unittest.TestCase):
    def test_the_photo_is_in_the_card_and_the_drawer_and_the_others_keep_their_initial(self):
        for loc in (EN, AR):
            html, editor, uri = rendered(loc)
            card = html.split(f'<a class="v-card" href="#/editor/{editor}"', 1)[1].split("</a>", 1)[0]
            drawer = html.split(f'<template id="vp-{editor}">', 1)[1].split("</template>", 1)[0]
            self.assertIn(f'<img src="{uri}"', card)
            self.assertIn(f'<img src="{uri}"', drawer)
            others = [part.split("</a>", 1)[0] for part in html.split('<a class="v-card" href="#/editor/')[1:] if not part.startswith(editor)]
            self.assertTrue(others and all("<img" not in card for card in others))
        self.assertIsNone(document(VERDICTS_JSON)["editors"][0]["photo_url"])      # verdicts.json never carries the photo

    def test_the_site_build_embeds_photos_from_the_photo_directory(self):
        directory = Path(tempfile.mkdtemp(prefix="atlas-photos-"))
        out = Path(tempfile.mkdtemp(prefix="atlas-photo-site-"))
        self.addCleanup(shutil.rmtree, directory, True)
        self.addCleanup(shutil.rmtree, out, True)
        editor = document(VERDICTS_JSON)["editors"][0]["editor_id"]
        (directory / f"{editor}.png").write_bytes(png())
        with mock.patch.dict(os.environ, {photos.ENV: str(directory)}):
            result = profile_cli.reconstruct_extract(showcase_extract(), CONTRACT)
            profile_cli.build_all(result, CONTRACT, out, GENERATED_AT)
        for locale in ("en", "ar"):
            self.assertIn("data:image/png;base64,iVBORw0KGgo", (out / site_layout.dashboard_html(locale)).read_text(encoding="utf-8"))
        self.assertIsNone(json.loads((out / VERDICTS_JSON).read_text())["editors"][0]["photo_url"])


LOADED = """
    await wait(400);
    const card = document.querySelector('.v-card img'); const initials = [...document.querySelectorAll('.v-card .v-av')].filter(a => !a.querySelector('img')).length;
    location.hash = '#/editor/' + card.closest('.v-card').dataset.editorId; await wait(400);
    const drawer = document.querySelector('#vprofile .v-av img');
    return {card: card.naturalWidth > 0, drawer: !!drawer && drawer.naturalWidth > 0, initials};
"""


@unittest.skipIf(chrome() is None, "headless Chrome is not available")
class PhotoBrowserTests(unittest.TestCase):
    def test_the_photo_loads_in_card_and_drawer(self):
        for loc in (EN, AR):
            html, _, _ = rendered(loc)
            result = run_scenario(html, LOADED, width=1280, height=900)
            self.assertTrue(result["card"] and result["drawer"], (loc, result))
            self.assertGreater(result["initials"], 0, result)


if __name__ == "__main__":
    unittest.main()
