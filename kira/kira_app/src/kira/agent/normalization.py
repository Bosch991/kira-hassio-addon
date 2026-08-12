"""Shared text normalization for German assistant input."""

from __future__ import annotations

import re
import unicodedata

_MOJIBAKE_REPLACEMENTS = {
    "\u00c3\u00a4": "ae",
    "\u00c3\u00b6": "oe",
    "\u00c3\u00bc": "ue",
    "\u00c3\u0178": "ss",
    "\u00c3\u0192\u00c2\u00a4": "ae",
    "\u00c3\u0192\u00c2\u00b6": "oe",
    "\u00c3\u0192\u00c2\u00bc": "ue",
}

_GERMAN_TRANSLATION = str.maketrans(
    {
        "\u00e4": "ae",
        "\u00f6": "oe",
        "\u00fc": "ue",
        "\u00df": "ss",
    }
)


def normalize_text(value: str) -> str:
    """Return a stable lowercase representation for matching."""
    text = value.strip().lower()
    for broken, replacement in _MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(broken.lower(), replacement)
    text = text.translate(_GERMAN_TRANSLATION)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    text = re.sub(r"[^a-z0-9_.%+-]+", " ", text)
    return " ".join(text.split())


def text_tokens(value: str) -> set[str]:
    """Return normalized non-empty words."""
    return {token for token in normalize_text(value).replace("_", " ").split() if token}
