"""Text helpers shared by the builder and the site (no heavy imports)."""

from __future__ import annotations

import re
import unicodedata


def search_key(name: str) -> str:
    """'Nikola Jokić' -> 'nikola jokic': accent-free, lower-case, no punctuation."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return re.sub(r"[^a-z0-9 ]+", "", text.replace("-", " ")).strip()
