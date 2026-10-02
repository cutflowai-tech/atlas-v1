"""HTTP plumbing shared by the provider and memory clients: credentials never follow a redirect, and responses are bounded.

``urllib.request.urlopen`` follows 301/302/303/307/308 and re-sends every header, ``Authorization`` included, to wherever the
redirect points (another host, or plain http). Both external services are called at fixed API URLs, so a redirect is never
expected: ``open_no_redirect`` returns it as an HTTP error status instead of following it.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any

MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class ResponseTooLarge(OSError):
    """A response body exceeded the configured bound."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None     # urllib then raises HTTPError(code): the caller sees a 3xx status, nothing is sent to ``newurl``


_OPENER = urllib.request.build_opener(_NoRedirect)


def read_bounded(response: Any, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    body = response.read(limit + 1) or b""
    if len(body) > limit:
        raise ResponseTooLarge(f"the response exceeded {limit} bytes")
    return bytes(body)


def open_no_redirect(request: urllib.request.Request, *, timeout: float, limit: int = MAX_RESPONSE_BYTES) -> tuple[int, Any, bytes]:
    """``(status, headers, body)`` of one request; a redirect is returned as its 3xx status, never followed."""
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, response.headers, read_bounded(response, limit)
    except urllib.error.HTTPError as error:
        return error.code, error.headers, read_bounded(error, limit)
