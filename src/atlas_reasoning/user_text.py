"""Validation of text typed by management (notes, answers, teachings, identities).

Text is stored as plain text, never as HTML: it is Unicode-normalized (NFC), line endings become ``\\n``, control characters other
than newline and tab are refused, invisible bidirectional overrides (which can make text display differently from what is stored)
are removed, and length is bounded. Escaping happens when text is rendered (``human_context_html``), never by altering what was
stored.
"""

from __future__ import annotations

import re
import unicodedata

_BIDI_CONTROLS = re.compile("[\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]")
_FORBIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_IDENTITY = 200


class InvalidText(ValueError):
    """User text that cannot be stored. ``code`` is stable for API responses."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def clean_text(value: object, *, field: str, max_length: int, min_length: int = 1) -> str:
    if not isinstance(value, str):
        raise InvalidText("INVALID_TYPE", f"{field} must be text")
    text = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    text = _BIDI_CONTROLS.sub("", text).strip()
    if _FORBIDDEN.search(text):
        raise InvalidText("CONTROL_CHARACTERS", f"{field} contains control characters")
    if len(text) < min_length:
        raise InvalidText("EMPTY", f"{field} must not be empty")
    if len(text) > max_length:
        raise InvalidText("TOO_LONG", f"{field} is limited to {max_length} characters")
    return text


def clean_identity(value: object, *, field: str = "author") -> str | None:
    """An author identity (from the authenticated session), or ``None`` when unknown."""
    if value is None:
        return None
    text = clean_text(value, field=field, max_length=MAX_IDENTITY)
    if "\n" in text or "\t" in text:
        raise InvalidText("INVALID_IDENTITY", f"{field} must be a single line")
    return text


def normalized_for_comparison(text: str) -> str:
    """Case-, width- and whitespace-insensitive form used to compare two texts (duplicate answers, duplicate questions)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()
