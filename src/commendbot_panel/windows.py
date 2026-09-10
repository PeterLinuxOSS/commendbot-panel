"""Everything that only works on Windows, behind functions that degrade elsewhere.

Keeping the platform calls here is what lets the rest of the package be imported
and unit-tested on any machine. Each helper states what it does when the
platform or the optional dependency is missing.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import uuid
from pathlib import Path

from .config import SettingsStore, UserSettings, from_mapping, to_mapping

IS_WINDOWS = sys.platform == "win32"

# Process creation flags. Zero elsewhere, so the calls stay portable.
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0
CREATE_NEW_CONSOLE = 0x00000010 if IS_WINDOWS else 0

_REGISTRY_KEY = r"Software\CommendBotPR"
_SETTINGS_SUBKEY = "Settings"


# --- machine identity -----------------------------------------------------


def machine_id() -> str:
    """A stable per-machine identifier, used to tie a licence to one PC.

    The original shelled out to ``wmic csproduct get uuid`` and cut the result
    out of the ``str(bytes)`` repr with fixed offsets. ``wmic`` was removed from
    Windows 11 24H2, so on a current install that returns an empty string and
    every machine ends up sharing one ID (AUDIT.md B8).

    Order of preference: the registry ``MachineGuid``, then PowerShell's CIM
    query, then a hash of the network interface address so the function always
    returns something deterministic.
    """
    for source in (_machine_guid_from_registry, _machine_uuid_from_powershell):
        try:
            value = source()
        except Exception:  # noqa: BLE001 - any failure just moves to the next source
            value = None
        if value:
            return value
    return _machine_id_fallback()


def _machine_guid_from_registry() -> str | None:
    """``HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid``, set at install time."""
    if not IS_WINDOWS:
        return None
    import winreg  # noqa: PLC0415 - Windows-only

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
        0,
        winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
    ) as key:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
    return str(value).strip() or None


def _machine_uuid_from_powershell() -> str | None:
    """The SMBIOS UUID — the same value the original ``wmic`` call returned."""
    if not IS_WINDOWS:
        return None
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_ComputerSystemProduct).UUID",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        creationflags=CREATE_NO_WINDOW,
    )
    return completed.stdout.strip() or None


def _machine_id_fallback() -> str:
    """Deterministic ID for non-Windows hosts and for locked-down machines."""
    return hashlib.sha256(str(uuid.getnode()).encode()).hexdigest()[:32]


# --- settings in the registry --------------------------------------------


class RegistrySettingsStore(SettingsStore):
    """Reads and writes ``HKCU\\Software\\CommendBotPR\\Settings``.

    The original also kept the panel password here in clear text and rewrote it
    on every login (AUDIT.md B5). Only the login name is remembered now.
    """

    def load(self) -> UserSettings:
        return from_mapping(self._read_subkey(_SETTINGS_SUBKEY))

    def save(self, settings: UserSettings) -> None:
        self._write_subkey(_SETTINGS_SUBKEY, to_mapping(settings))

    def _read_subkey(self, subkey: str) -> dict[str, object]:
        """Return every value under the subkey; an empty dict if it is absent."""
        if not IS_WINDOWS:
            return {}
        import winreg  # noqa: PLC0415 - Windows-only

        path = f"{_REGISTRY_KEY}\\{subkey}" if subkey else _REGISTRY_KEY
        values: dict[str, object] = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    values[name] = value
                    index += 1
        except FileNotFoundError:
            return {}
        return values

    def _write_subkey(self, subkey: str, values: dict[str, object]) -> None:
        """Create the subkey if needed and write every value into it."""
        if not IS_WINDOWS:
            return
        import winreg  # noqa: PLC0415 - Windows-only

        path = f"{_REGISTRY_KEY}\\{subkey}" if subkey else _REGISTRY_KEY
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as key:
            for name, value in values.items():
                if isinstance(value, (bool, int)):
                    winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, int(value))
                else:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))


# --- foreground windows and processes ------------------------------------


class ForegroundError(RuntimeError):
    """Raised when a window handle can no longer be used."""


def window_exists(hwnd: int) -> bool:
    """True while the window with this handle is still alive."""
    if not IS_WINDOWS:
        return False
    import win32gui  # noqa: PLC0415 - Windows-only

    return bool(win32gui.IsWindow(hwnd))


def bring_to_front(hwnd: int) -> tuple[int, int, int, int]:
    """Focus a window and return its client area as ``(left, top, right, bottom)``.

    Raises:
        ForegroundError: if the handle is stale or this is not Windows.
    """
    if not IS_WINDOWS:
        raise ForegroundError("window handling is only implemented on Windows")
    import win32gui  # noqa: PLC0415 - Windows-only

    try:
        win32gui.SetForegroundWindow(hwnd)
        rect = win32gui.GetClientRect(hwnd)
        left, top = win32gui.ClientToScreen(hwnd, (rect[0], rect[1]))
    except Exception as exc:  # noqa: BLE001 - pywin32 raises bare pywintypes.error
        raise ForegroundError(f"window {hwnd} is no longer usable") from exc

    return (left, top, left + rect[2] - rect[0], top + rect[3] - rect[1])


def find_windows_by_title(title: str) -> list[int]:
    """Handles of every visible top-level window whose title contains ``title``."""
    if not IS_WINDOWS:
        return []
    import win32gui  # noqa: PLC0415 - Windows-only

    handles: list[int] = []

    def _collect(hwnd: int, _extra: object) -> None:
        if win32gui.IsWindowVisible(hwnd) and title in win32gui.GetWindowText(hwnd):
            handles.append(hwnd)

    win32gui.EnumWindows(_collect, None)
    return handles


def kill_processes(names: set[str]) -> int:
    """Terminate every running process whose executable name is in ``names``.

    Returns the number of processes killed. A missing ``psutil`` is not fatal —
    the caller only loses the ability to clean up.
    """
    try:
        import psutil  # noqa: PLC0415 - optional dependency
    except ImportError:  # pragma: no cover - depends on the environment
        return 0

    killed = 0
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info.get("name") or "").lower() in names:
                process.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return killed


def open_steam_url(url: str) -> None:
    """Hand a ``steam://`` URL to the OS so the Steam client acts on it."""
    import webbrowser  # noqa: PLC0415 - only needed on this path

    webbrowser.open_new(url)


def default_steam_path() -> Path:
    """The usual 64-bit Windows install location, used to pre-fill the settings."""
    return Path(r"C:/Program Files (x86)/Steam")


def default_csgo_path() -> Path:
    """The usual CS:GO location inside a default Steam library."""
    return (
        default_steam_path() / "steamapps" / "common" / "Counter-Strike Global Offensive"
    )
