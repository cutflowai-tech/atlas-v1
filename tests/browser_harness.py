"""Drive a rendered Atlas page in headless Chrome and read back what a scenario observed.

The pages are static and self-contained, so a behaviour test needs no server: the page is written to a temporary file, Chrome loads
it, and the test talks to Chrome over the DevTools protocol on a pipe (``--remote-debugging-pipe``, standard library only). A
scenario is an async JavaScript function body evaluated in the page; ``Browser.key`` sends real key presses (Tab, Escape) so focus
behaviour is tested as a user would meet it.

Tests using it are skipped when no Chrome is installed or when ``ATLAS_BROWSER_TESTS=0``.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Self

CANDIDATES = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "google-chrome-stable", "chromium",
              "chromium-browser")
PRELUDE = "const wait = ms => new Promise(r => setTimeout(r, ms));"
KEYS = {"Tab": ("Tab", 9), "Escape": ("Escape", 27), "Enter": ("Enter", 13)}


def chrome() -> str | None:
    if os.environ.get("ATLAS_BROWSER_TESTS") == "0":
        return None
    configured = os.environ.get("ATLAS_CHROME")
    for candidate in ([configured] if configured else []) + list(CANDIDATES):
        path = candidate if os.path.isabs(candidate) else shutil.which(candidate)
        if path and os.path.exists(path):
            return path
    return None


class Browser:
    """One headless Chrome with one page, controlled over the DevTools pipe."""

    def __init__(self, *, width: int = 1280, height: int = 900, dark: bool = True, mobile: bool = False) -> None:
        binary = chrome()
        if binary is None:
            raise RuntimeError("no Chrome available")
        self._tmp = tempfile.TemporaryDirectory(prefix="atlas-browser-")
        to_chrome_r, self._to_chrome = os.pipe()
        self._from_chrome, from_chrome_w = os.pipe()

        def fds() -> None:   # Chrome reads commands on fd 3 and writes replies on fd 4 (both inheritable)
            read, write = os.dup(to_chrome_r), os.dup(from_chrome_w)   # never dup2 a descriptor onto itself (it stays close-on-exec)
            os.dup2(read, 3)
            os.dup2(write, 4)

        args = [binary, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                "--remote-debugging-pipe", f"--user-data-dir={Path(self._tmp.name) / 'profile'}", "about:blank"]
        if os.name == "posix" and os.uname().sysname == "Linux":
            args.insert(1, "--no-sandbox")
        self._process = subprocess.Popen(args, preexec_fn=fds, close_fds=False,  # noqa: PLW1509 - tests are single-threaded
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        self._buffer = b""
        self._id = 0
        self._events: list[dict[str, Any]] = []
        target = self._call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self._session = self._call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile})
        self.call("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark" if dark else "light"}]})

    # ------------------------------------------------------------------ protocol
    def _send(self, message: dict[str, Any]) -> int:
        self._id += 1
        message["id"] = self._id
        os.write(self._to_chrome, json.dumps(message).encode() + b"\0")
        return self._id

    def _read(self, deadline: float) -> dict[str, Any]:
        while b"\0" not in self._buffer:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self._from_chrome], [], [], left)[0]:
                raise TimeoutError("Chrome did not answer")
            chunk = os.read(self._from_chrome, 1 << 16)
            if not chunk:
                raise RuntimeError("Chrome closed the pipe")
            self._buffer += chunk
        raw, self._buffer = self._buffer.split(b"\0", 1)
        return json.loads(raw)

    def _call(self, method: str, params: dict[str, Any] | None = None, session: str | None = None, timeout: float = 30) -> dict[str, Any]:
        message: dict[str, Any] = {"method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        wanted = self._send(message)
        deadline = time.monotonic() + timeout
        while True:
            reply = self._read(deadline)
            if reply.get("id") == wanted:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})
            if "method" in reply:
                self._events.append(reply)

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30) -> dict[str, Any]:
        return self._call(method, params, self._session, timeout)

    def _wait_event(self, method: str, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while True:
            for i, event in enumerate(self._events):
                if event.get("method") == method:
                    del self._events[: i + 1]
                    return
            self._events.append(self._read(deadline))

    # ------------------------------------------------------------------ page
    def open(self, page: str, fragment: str = "") -> None:
        path = Path(self._tmp.name) / "page.html"
        path.write_text(page, encoding="utf-8")
        self._events.clear()
        self.call("Page.navigate", {"url": path.as_uri() + (f"#{fragment}" if fragment else "")})
        self._wait_event("Page.loadEventFired")

    def run(self, scenario: str, timeout: float = 30) -> Any:
        """Evaluate an async function body in the page and return its (JSON) value."""
        result = self.call("Runtime.evaluate", {"expression": f"(async () => {{ {PRELUDE} {scenario} }})()", "awaitPromise": True,
                                                "returnByValue": True}, timeout)
        if "exceptionDetails" in result:
            raise AssertionError(f"scenario failed: {result['exceptionDetails']}")
        return result["result"].get("value")

    def screenshot(self, path: Path, *, selector: str | None = None, full_page: bool = False) -> None:
        """PNG of the viewport, the whole page, or one element (scrolled into view)."""
        params: dict[str, Any] = {"format": "png"}
        if selector or full_page:
            box = self.run(f"""
                const el = {json.dumps(selector)} ? document.querySelector({json.dumps(selector)}) : document.documentElement;
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {{x: r.left + window.scrollX, y: r.top + window.scrollY, width: Math.ceil(r.width),
                         height: Math.ceil({json.dumps(full_page)} ? document.documentElement.scrollHeight : r.height)}};
            """)
            if box is None:
                raise AssertionError(f"no element {selector!r}")
            params.update({"captureBeyondViewport": True, "clip": {**box, "scale": 1}})
        data = self.call("Page.captureScreenshot", params, timeout=60)["data"]
        Path(path).write_bytes(base64.b64decode(data))

    def key(self, name: str, shift: bool = False) -> None:
        key, code = KEYS[name]
        modifiers = 8 if shift else 0
        for kind in ("rawKeyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": key, "windowsVirtualKeyCode": code, "modifiers": modifiers})

    def close(self) -> None:
        with contextlib.suppress(Exception):   # best effort; the process is killed below anyway
            self._call("Browser.close", timeout=5)
        try:
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._process.kill()
        os.close(self._to_chrome)
        os.close(self._from_chrome)
        self._tmp.cleanup()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def run_scenario(page: str, scenario: str, *, width: int = 1280, height: int = 900, fragment: str = "", dark: bool = True) -> Any:
    """Open ``page`` at ``#fragment`` in a fresh browser and return what ``scenario`` returns."""
    with Browser(width=width, height=height, dark=dark) as browser:
        browser.open(page, fragment)
        return browser.run(scenario)
