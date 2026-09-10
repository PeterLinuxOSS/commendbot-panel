"""Rewriting CS:GO's ``gameinfo.txt``.

The runner stamps the account's SteamID64 into the ``game`` field before every
launch. That field is what the game shows as the mod name, so with several
clients running side by side it is the only way to tell the windows apart.

The template is Valve's stock CS:GO ``gameinfo.txt`` with the ``game`` value
replaced by a placeholder; nothing else in it is modified.
"""

from __future__ import annotations

from pathlib import Path

_ACCOUNT_PLACEHOLDER = "%ACCOUNT%"

GAMEINFO_TEMPLATE = f"""
"GameInfo"
{{
\tgame\t"{_ACCOUNT_PLACEHOLDER}"
\ttitle\t"COUNTER-STRIKE'"
\ttitle2\t"GO"
\ttype multiplayer_only
\tnomodels 1
\tnohimodel 1
\tnocrosshair 0
\tbots 1
\thidden_maps
\t{{
\t\t"test_speakers"\t\t1
\t\t"test_hardware"\t\t1
\t}}
\tnodegraph 0
\tSupportsXbox360 1
\tSupportsDX8\t0
\tGameData\t"csgo.fgd"

\tFileSystem
\t{{
\t\tSteamAppId\t\t\t\t730
\t\tToolsAppId\t\t\t\t211

\t\tSearchPaths
\t\t{{
\t\t\tGame\t\t\t\t|gameinfo_path|.
\t\t\tGame\t\t\t\tcsgo
\t\t}}
\t}}
}}
"""


def gameinfo_path(csgo_path: Path) -> Path:
    """Location of ``gameinfo.txt`` inside a CS:GO installation."""
    return csgo_path / "csgo" / "gameinfo.txt"


def console_log_path(csgo_path: Path) -> Path:
    """Location of the console log the runner tails."""
    return csgo_path / "csgo" / "console.log"


def render_gameinfo(steam_id64: int) -> str:
    """Return the ``gameinfo.txt`` body tagged with this account's ID."""
    return GAMEINFO_TEMPLATE.replace(_ACCOUNT_PLACEHOLDER, str(steam_id64))


def write_gameinfo(csgo_path: Path, steam_id64: int) -> Path:
    """Write the tagged ``gameinfo.txt`` and return the path it was written to."""
    target = gameinfo_path(csgo_path)
    target.write_text(render_gameinfo(steam_id64), encoding="utf-8")
    return target
