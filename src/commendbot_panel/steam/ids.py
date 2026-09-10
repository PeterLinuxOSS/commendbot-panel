"""Conversions between the Steam identifier forms this program deals with.

Steam exposes the same account as a 64-bit ID (``76561198…``), as a 32-bit
account ID (used for the ``userdata/<id>`` folder) and as a profile URL. The
original code inlined the magic offset in four places and had no validation at
all, so a mistyped profile link surfaced as a ``TypeError`` several calls later.
"""

from __future__ import annotations

import re

from ..constants import STEAM_ID64_BASE, STEAM_ID64_LENGTH

# Matches both /profiles/<id64> and /id/<vanity> forms.
_PROFILE_URL = re.compile(
    r"steamcommunity\.com/(?P<kind>profiles|id)/(?P<value>[^/?#]+)", re.IGNORECASE
)


def to_steam_id32(steam_id64: int) -> int:
    """Return the 32-bit account ID that names the ``userdata`` folder.

    Raises:
        ValueError: if the value is below the base offset and so cannot be an ID64.
    """
    if steam_id64 < STEAM_ID64_BASE:
        raise ValueError(f"{steam_id64} is not a SteamID64")
    return steam_id64 - STEAM_ID64_BASE


def to_steam_id64(steam_id32: int) -> int:
    """Inverse of :func:`to_steam_id32`."""
    if steam_id32 < 0:
        raise ValueError(f"{steam_id32} is not a Steam account ID")
    return steam_id32 + STEAM_ID64_BASE


def looks_like_steam_id64(text: str) -> bool:
    """True when ``text`` is a plausible SteamID64 in decimal form."""
    text = text.strip()
    return len(text) == STEAM_ID64_LENGTH and text.isdigit()


def parse_steam_id(text: str, *, resolve_vanity=None) -> int | None:
    """Turn user input into a SteamID64, or return ``None`` if it is not one.

    Accepts a bare 17-digit ID, a ``/profiles/<id64>`` link, or a ``/id/<name>``
    vanity link. Vanity names need a lookup, which is injected via
    ``resolve_vanity`` so that this function stays offline and testable; when no
    resolver is supplied a vanity link simply yields ``None``.
    """
    text = (text or "").strip()
    if not text:
        return None

    if looks_like_steam_id64(text):
        return int(text)

    match = _PROFILE_URL.search(text)
    if not match:
        return None

    value = match.group("value")
    if match.group("kind").lower() == "profiles":
        return int(value) if looks_like_steam_id64(value) else None

    if resolve_vanity is None:
        return None
    resolved = resolve_vanity(value)
    return int(resolved) if resolved else None
