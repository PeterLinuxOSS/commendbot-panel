"""Building the command lines that start Steam, CS:GO and the runners.

Command construction is separated from execution so the arguments can be
asserted in a test without spawning anything.

A note on the password. Steam only accepts credentials on its own command line,
so ``steam.exe -login <user> <pass>`` is unavoidable and the password is briefly
visible in the process list. What *was* avoidable is the panel repeating it on
the runner's command line as well (AUDIT.md B1): the runner now receives it over
the authenticated control channel instead, so it exists in one process list
entry rather than two.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..constants import CSGO_APP_ID
from .ids import to_steam_id32


@dataclass(frozen=True)
class Installation:
    """Where Steam and CS:GO live on this machine."""

    steam_path: Path
    csgo_path: Path

    @property
    def steam_executable(self) -> Path:
        """Full path to ``steam.exe``."""
        return self.steam_path / "steam.exe"

    def user_data(self, steam_id64: int) -> Path:
        """``userdata/<account id>/730`` for one account."""
        return (
            self.steam_path
            / "userdata"
            / str(to_steam_id32(steam_id64))
            / str(CSGO_APP_ID)
        )

    def game_config(self) -> Path:
        """``csgo/cfg``, where autoexec and friends are read from."""
        return self.csgo_path / "csgo" / "cfg"


def build_steam_login_command(
    installation: Installation,
    account: str,
    password: str,
    extra_arguments: tuple[str, ...] = (),
) -> list[str]:
    """The argv that signs Steam in as ``account``."""
    return [
        str(installation.steam_executable),
        "-login",
        account,
        password,
        *extra_arguments,
    ]


def build_shutdown_command(installation: Installation) -> list[str]:
    """The argv that asks a running Steam client to exit."""
    return [str(installation.steam_executable), "-shutdown"]


def build_runner_command(
    runner_command: list[str],
    installation: Installation,
    steam_id64: int,
    *,
    window_offset: int = 0,
    launch_arguments: str = "",
) -> list[str]:
    """The argv that starts one runner process.

    ``runner_command`` is how the runner is invoked on this install — a frozen
    build is one executable, a source checkout is ``[python, "-m", ...]``.
    ``window_offset`` tiles the game windows horizontally so several accounts
    running at once do not stack on top of each other. Credentials are *not*
    part of this list; they arrive over the control channel.
    """
    command = [
        *runner_command,
        "--steam-path",
        str(installation.steam_path),
        "--csgo-path",
        str(installation.csgo_path),
        "--steam-id",
        str(steam_id64),
    ]
    if launch_arguments.strip():
        command += ["--launch-arguments", launch_arguments.strip()]
    if window_offset:
        command += ["--window-x", str(window_offset)]
    return command


def spawn(
    command: list[str],
    *,
    creationflags: int = 0,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    """Start a detached process.

    ``env`` replaces the child's whole environment when given; the caller is
    expected to have merged it with ``os.environ`` already.

    ``shell=True`` is deliberately not used. The original passed a list *and*
    ``shell=True``, which on Windows hands only the first element to the shell
    and quietly loses the rest as soon as a path contains a space
    (AUDIT.md B2).
    """
    return subprocess.Popen(  # noqa: S603
        command, creationflags=creationflags, env=env
    )


def copy_tree(source: Path, target: Path) -> int:
    """Copy every file from ``source`` into ``target``, creating it if needed.

    Returns the number of files copied. In the original, one of the three copy
    loops had the ``shutil.copy`` nested inside ``if not
    os.path.exists(target_folder)`` — and the folder had just been created two
    lines above, so that branch never ran and those files were never installed
    (AUDIT.md A4). All three call sites now share this one implementation.
    """
    if not source.is_dir():
        return 0

    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    for entry in sorted(source.iterdir()):
        if not entry.is_file():
            continue
        try:
            shutil.copy2(entry, target / entry.name)
        except PermissionError:
            # A file the game currently holds open is not worth aborting for.
            continue
        copied += 1
    return copied


def install_config_payload(
    payload_root: Path, installation: Installation, steam_id64: int
) -> dict[str, int]:
    """Copy the bundled CS:GO configuration into the account's Steam folders.

    ``payload_root`` is the ``cfg`` directory shipped alongside the runner and
    holds three sub-directories:

    ``local``     -> ``userdata/<id>/730/local``     (per-account game state)
    ``userdata``  -> ``userdata/<id>/730/local/cfg`` (per-account config)
    ``game/cfg``  -> ``<csgo>/csgo/cfg``             (shared autoexec)

    Returns how many files each of the three copies installed.
    """
    user_data = installation.user_data(steam_id64)
    return {
        "local": copy_tree(payload_root / "local", user_data / "local"),
        "userdata": copy_tree(payload_root / "userdata", user_data / "local" / "cfg"),
        "game": copy_tree(payload_root / "game" / "cfg", installation.game_config()),
    }


def run_game_url() -> str:
    """``steam://`` URL that launches CS:GO in an already-running client."""
    return f"steam://rungameid/{CSGO_APP_ID}"
