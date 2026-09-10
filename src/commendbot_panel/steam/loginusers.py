"""Reading Steam's ``config/loginusers.vdf``.

The panel needs the SteamID64 that belongs to a given account name, and the only
offline source for that mapping is the VDF file Steam keeps next to its
configuration. Parsing is split from file access so the parser can be tested
against a literal fixture.
"""

from __future__ import annotations

from pathlib import Path


def login_users_path(steam_path: Path) -> Path:
    """Location of ``loginusers.vdf`` inside a Steam installation."""
    return steam_path / "config" / "loginusers.vdf"


def parse_login_users(text: str) -> dict[str, int]:
    """Map account name to SteamID64 for every account Steam has seen.

    Args:
        text: the contents of ``loginusers.vdf``.

    Returns:
        ``{"account_name": 76561198...}``. Account names are lower-cased,
        because Steam itself treats them case-insensitively while the file
        preserves whatever casing the user typed at first login.
    """
    users = _load_vdf(text)
    accounts: dict[str, int] = {}
    for steam_id, entry in (users.get("users") or {}).items():
        if not isinstance(entry, dict):
            continue
        name = entry.get("AccountName")
        if not name or not str(steam_id).isdigit():
            continue
        accounts[str(name).lower()] = int(steam_id)
    return accounts


def find_steam_id_by_account(text: str, account_name: str) -> int | None:
    """Return the SteamID64 for ``account_name``, or ``None`` if Steam never saw it."""
    return parse_login_users(text).get(account_name.strip().lower())


def _load_vdf(text: str) -> dict:
    """Parse VDF, preferring the ``vdf`` package and falling back to a small reader.

    The fallback exists so that the parser — and the tests that cover it — do not
    depend on an optional third-party package.
    """
    try:
        import vdf  # noqa: PLC0415 - optional dependency, imported lazily
    except ImportError:
        return _minimal_vdf(text)
    return vdf.loads(text)


def _minimal_vdf(text: str) -> dict:
    """Parse the small subset of VDF that ``loginusers.vdf`` uses.

    Only two constructs appear in that file: ``"key" { ... }`` for a nested
    block and ``"key"  "value"`` for a leaf. Anything else is ignored.
    """
    root: dict = {}
    stack: list[dict] = [root]
    pending_key: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        if line == "{":
            # The key seen on the previous line opens a block.
            block: dict = {}
            if pending_key is not None:
                stack[-1][pending_key] = block
                pending_key = None
            stack.append(block)
            continue

        if line == "}":
            if len(stack) > 1:
                stack.pop()
            continue

        tokens = _quoted_tokens(line)
        if len(tokens) == 1:
            pending_key = tokens[0]
        elif len(tokens) >= 2:
            stack[-1][tokens[0]] = tokens[1]

    return root


def _quoted_tokens(line: str) -> list[str]:
    """Split a VDF line into its double-quoted tokens."""
    tokens: list[str] = []
    inside = False
    current: list[str] = []
    for char in line:
        if char == '"':
            if inside:
                tokens.append("".join(current))
                current = []
            inside = not inside
        elif inside:
            current.append(char)
    return tokens
