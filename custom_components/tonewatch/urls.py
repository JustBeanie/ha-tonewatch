"""URL construction helpers shared by ToneWatch runtime components."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin


def recording_url(base_url: str, value: Any) -> str | None:
    """Build a token-free absolute recording URL from an API value."""
    if value in (None, ""):
        return None
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    path = str(value).lstrip("/")
    if not path.startswith("recordings/"):
        path = f"recordings/{path}"
    return urljoin(f"{base_url}/api/", path)
