"""Runtime configuration.

Two sources, deliberately kept apart:

``environment``
    Secrets and deployment details — the MongoDB URI and the token that guards
    the loopback control channel. Never written to disk by this program.

``user settings``
    Paths and toggles the operator changes in the settings screen. On Windows
    these live in ``HKCU\\Software\\CommendBotPR\\Settings``; elsewhere they fall
    back to a JSON file so the package stays importable and testable.

The original build had the database credentials as a literal in the source and
therefore in every distributed ``.exe`` (AUDIT.md S1). There is no default URI
here on purpose: without ``COMMENDBOT_MONGO_URI`` the panel refuses to start.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field, replace
from pathlib import Path

from .constants import DEFAULT_LAUNCH_ARGUMENTS, IPC_HOST, IPC_PORT
from .servers import GameServer, load_servers

ENV_MONGO_URI = "COMMENDBOT_MONGO_URI"
ENV_IPC_TOKEN = "COMMENDBOT_IPC_TOKEN"
ENV_SERVERS_FILE = "COMMENDBOT_SERVERS_FILE"


class ConfigError(RuntimeError):
    """Raised when a required piece of configuration is missing or unusable."""


@dataclass(frozen=True)
class UserSettings:
    """Operator-editable preferences. Safe to persist; contains no secrets."""

    steam_path: Path | None = None
    csgo_path: Path | None = None
    launch_arguments: str = DEFAULT_LAUNCH_ARGUMENTS
    auto_reconnect: bool = False
    auto_start: bool = False
    end_task: str = "Do nothing"
    remembered_login: str = ""

    @property
    def paths_are_valid(self) -> bool:
        """True when both configured directories actually exist on this machine."""
        return bool(
            self.steam_path
            and self.steam_path.is_dir()
            and self.csgo_path
            and self.csgo_path.is_dir()
        )


@dataclass(frozen=True)
class Settings:
    """Everything the application needs to run, resolved once at startup."""

    mongo_uri: str
    ipc_token: str
    servers: tuple[GameServer, ...]
    user: UserSettings = field(default_factory=UserSettings)
    ipc_host: str = IPC_HOST
    ipc_port: int = IPC_PORT

    def with_user(self, user: UserSettings) -> Settings:
        """Return a copy carrying updated user settings."""
        return replace(self, user=user)


def load_settings(
    store: SettingsStore | None = None,
    environ: dict[str, str] | None = None,
) -> Settings:
    """Assemble :class:`Settings` from the environment and the settings store.

    Raises:
        ConfigError: if ``COMMENDBOT_MONGO_URI`` is not set.
    """
    env = os.environ if environ is None else environ

    mongo_uri = env.get(ENV_MONGO_URI, "").strip()
    if not mongo_uri:
        raise ConfigError(
            f"{ENV_MONGO_URI} is not set. Copy .env.example to .env and fill in "
            "the connection string for your MongoDB deployment."
        )

    # A generated token is fine: the panel passes it to the runners it spawns,
    # so both ends agree without the operator having to configure anything.
    ipc_token = env.get(ENV_IPC_TOKEN, "").strip() or secrets.token_urlsafe(16)

    servers_file = env.get(ENV_SERVERS_FILE, "").strip()
    servers = load_servers(Path(servers_file)) if servers_file else ()

    store = store or default_store()
    return Settings(
        mongo_uri=mongo_uri,
        ipc_token=ipc_token,
        servers=servers,
        user=store.load(),
    )


class SettingsStore:
    """Persistence for :class:`UserSettings`. Subclassed per platform."""

    def load(self) -> UserSettings:  # pragma: no cover - interface
        raise NotImplementedError

    def save(self, settings: UserSettings) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class JsonSettingsStore(SettingsStore):
    """Settings in a JSON file. Used off Windows and by the test-suite."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> UserSettings:
        if not self.path.is_file():
            return UserSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt settings file must not stop the program from starting.
            return UserSettings()
        return from_mapping(raw)

    def save(self, settings: UserSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(to_mapping(settings), indent=2), encoding="utf-8")


def to_mapping(settings: UserSettings) -> dict[str, object]:
    """Flatten settings for storage. Paths become strings, ``None`` becomes ``""``."""
    return {
        "SteamPath": str(settings.steam_path or ""),
        "CSGOPath": str(settings.csgo_path or ""),
        "Arguments": settings.launch_arguments,
        "autoreconnect": settings.auto_reconnect,
        "autostart": settings.auto_start,
        "endtask": settings.end_task,
        "login": settings.remembered_login,
    }


def from_mapping(raw: dict[str, object]) -> UserSettings:
    """Rebuild settings from storage, dropping paths that no longer exist."""
    return UserSettings(
        steam_path=_existing_dir(raw.get("SteamPath")),
        csgo_path=_existing_dir(raw.get("CSGOPath")),
        launch_arguments=str(raw.get("Arguments") or DEFAULT_LAUNCH_ARGUMENTS),
        auto_reconnect=_as_bool(raw.get("autoreconnect")),
        auto_start=_as_bool(raw.get("autostart")),
        end_task=str(raw.get("endtask") or "Do nothing"),
        remembered_login=str(raw.get("login") or ""),
    )


def _existing_dir(value: object) -> Path | None:
    """Return ``value`` as a Path if it points at an existing directory."""
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_dir() else None


def _as_bool(value: object) -> bool:
    """Interpret registry DWORDs, JSON booleans and strings uniformly.

    The registry hands back ``0``/``1`` integers and the JSON store hands back
    real booleans. The original code did ``bool("0")`` on the wire format, which
    is ``True`` — that is why Auto-Reconnect could never be switched off
    (AUDIT.md A1).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def default_store() -> SettingsStore:
    """Pick the registry store on Windows, the JSON store everywhere else."""
    from .windows import IS_WINDOWS, RegistrySettingsStore  # noqa: PLC0415 - cycle

    if not IS_WINDOWS:
        return JsonSettingsStore(_fallback_settings_path())
    return RegistrySettingsStore()


def _fallback_settings_path() -> Path:
    """Location of the JSON settings file on non-Windows hosts."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "commendbot-panel" / "settings.json"
