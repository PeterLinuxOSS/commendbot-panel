"""One runner process: sign one account in, keep its client on a server.

Started by the panel, one per account. It talks to the panel over the loopback
control channel and watches the game's ``console.log`` to work out what the
client is doing — CS:GO has no other machine-readable status.

Rewritten from the original ``run/main.py``. Behavioural fixes, all listed in
AUDIT.md:

A3  the reconnect budget can now actually expire.
A4  the third configuration copy really runs.
A13 no ``raise "string"``; the disconnect path is an explicit branch.
A14 the "stalled on connect" retry fires when the account is *not* commending,
    which is the state it was meant for. The original condition ordering made
    that branch unreachable.
B1  the Steam password arrives over the control channel, not on argv.
B2  processes are spawned without ``shell=True``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..config import ENV_IPC_TOKEN, ENV_SERVERS_FILE
from ..constants import (
    CONNECTED_MESSAGE,
    CONSOLE_POLL_SECONDS,
    DISCONNECT_MESSAGES,
    FIRST_CONNECT_DELAY_SECONDS,
    STALLED_CONNECT_SECONDS,
    STEAM_SIGN_IN_WINDOW_TITLE,
)
from ..ipc import protocol
from ..ipc.client import ControlClient
from ..servers import GameServer, ServerLoad, first_or_none, load_servers
from ..servers import pick_best_server as choose_server
from ..steam import gameinfo, launcher
from ..windows import (
    CREATE_NO_WINDOW,
    ForegroundError,
    bring_to_front,
    find_windows_by_title,
    kill_processes,
    open_steam_url,
    window_exists,
)

log = logging.getLogger("commendbot.runner")

# Processes this runner is allowed to terminate when it shuts down.
_OWNED_PROCESSES = {"csgo.exe", "steam.exe"}


@dataclass
class RunnerState:
    """Everything the poll loop needs to know between iterations."""

    auto_reconnect: bool = True
    #: True once the game has produced any console output at all.
    client_awake: bool = False
    #: True once the account is on a server and the panel has been told.
    commending: bool = False
    #: Seconds spent neither connecting nor commending.
    idle_seconds: int = 0
    stopping: threading.Event = field(default_factory=threading.Event)


class Runner:
    """Drives one account for the lifetime of the process."""

    def __init__(
        self,
        client: ControlClient,
        installation: launcher.Installation,
        steam_id64: int,
        servers: tuple[GameServer, ...],
        *,
        launch_arguments: str = "",
        payload_root: Path | None = None,
    ) -> None:
        self.client = client
        self.installation = installation
        self.steam_id64 = steam_id64
        self.servers = servers
        self.launch_arguments = launch_arguments
        self.payload_root = payload_root
        self.state = RunnerState()
        self.console = gameinfo.console_log_path(installation.csgo_path)

    # --- setup ------------------------------------------------------------

    def prepare(self) -> None:
        """Install the configuration payload and tag ``gameinfo.txt``."""
        if self.payload_root is not None:
            copied = launcher.install_config_payload(
                self.payload_root, self.installation, self.steam_id64
            )
            log.info("installed config payload: %s", copied)

        gameinfo.write_gameinfo(self.installation.csgo_path, self.steam_id64)
        self._truncate_console()

    def sign_in(self, account: str, password: str) -> None:
        """Start Steam signed in as ``account`` and launch the game."""
        command = launcher.build_steam_login_command(
            self.installation,
            account,
            password,
            tuple(self.launch_arguments.split()) if self.launch_arguments else (),
        )
        launcher.spawn(command, creationflags=CREATE_NO_WINDOW)
        log.info("steam launching for %s", self.steam_id64)

    # --- the message thread ----------------------------------------------

    def handle(self, verb: str, args: tuple[str, ...]) -> None:
        """React to one message from the panel."""
        if verb == protocol.CREDENTIALS and len(args) >= 2:
            self.sign_in(args[0], args[1])

        elif verb == protocol.SETTINGS:
            flags = dict(a.split("=", 1) for a in args if "=" in a)
            if "autoreconnect" in flags:
                self.state.auto_reconnect = protocol.parse_bool(flags["autoreconnect"])
                log.info("auto-reconnect is now %s", self.state.auto_reconnect)

        elif verb == protocol.CONNECT:
            target = args[0] if args else self._server_url()
            if target:
                open_steam_url(target)

        elif verb == protocol.LAUNCH:
            open_steam_url(launcher.run_game_url())

        elif verb == protocol.RESTART:
            # The panel wants the "already commending" latch cleared.
            self.state.commending = False
            self.state.idle_seconds = 0

        elif verb == protocol.FIND_LOGIN:
            self._report_login_window()

        elif verb == protocol.CLOSE:
            log.info("panel asked us to stop")
            self.shutdown()

        elif verb == protocol.DENIED:
            log.error("panel refused us: %s", " ".join(args))
            self.state.stopping.set()

    def _report_login_window(self) -> None:
        """Tell the panel the handle of the Steam Guard window, if it is up."""
        handles = find_windows_by_title(STEAM_SIGN_IN_WINDOW_TITLE)
        if not handles:
            # It can take a few seconds to appear after Steam starts.
            time.sleep(5)
            handles = find_windows_by_title(STEAM_SIGN_IN_WINDOW_TITLE)
        if not handles:
            log.info("no Steam sign-in window yet")
            return

        hwnd = handles[0]
        try:
            bring_to_front(hwnd)
        except ForegroundError:
            log.info("sign-in window vanished before it could be focused")
            return
        if window_exists(hwnd):
            self.client.send(protocol.LOGIN_WINDOW, hwnd)

    # --- the poll loop ----------------------------------------------------

    def run(self) -> None:
        """Watch the console log until the panel or the operator stops us."""
        while not self.state.stopping.is_set():
            try:
                self._poll_once()
            except OSError as exc:
                # A transient file lock on console.log is not worth dying for.
                log.warning("console poll failed: %s", exc)
            self.state.stopping.wait(CONSOLE_POLL_SECONDS)

    def _poll_once(self) -> None:
        """One pass over the console log."""
        if not self.console.exists():
            log.debug("console log does not exist yet")
            return
        if not self.state.auto_reconnect:
            return

        lines = self._drain_console()

        if not self.state.client_awake:
            if not lines:
                return
            # First output means the client is alive; give it time to settle.
            self.state.client_awake = True
            log.info("client is up, waiting %ss", FIRST_CONNECT_DELAY_SECONDS)
            if self.state.stopping.wait(FIRST_CONNECT_DELAY_SECONDS):
                return
            self._connect_to_server()
            return

        if any(msg in line for line in lines for msg in DISCONNECT_MESSAGES):
            log.info("dropped from the server, reconnecting")
            self.state.commending = False
            self._connect_to_server()
            return

        if any(CONNECTED_MESSAGE in line for line in lines):
            if not self.state.commending:
                self.state.commending = True
                self.state.idle_seconds = 0
                log.info("on a server, commending can start")
                self.client.send(protocol.STARTED)
            return

        # Nothing happened this round. Only an account that is *not* commending
        # is stuck; one that is commending is simply quiet.
        if self.state.commending:
            return

        self.state.idle_seconds += CONSOLE_POLL_SECONDS
        if self.state.idle_seconds >= STALLED_CONNECT_SECONDS:
            self.state.idle_seconds = 0
            log.info("no progress for %ss, trying again", STALLED_CONNECT_SECONDS)
            self._connect_to_server()

    def _drain_console(self) -> list[str]:
        """Read the console log and truncate it, so each line is seen once."""
        if self.console.stat().st_size == 0:
            return []
        with self.console.open(encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
        self._truncate_console()
        return lines

    def _truncate_console(self) -> None:
        """Empty the console log without deleting it."""
        self.console.write_text("", encoding="utf-8")

    def _connect_to_server(self) -> None:
        """Send the client to the least busy server we can find."""
        url = self._server_url()
        if url is None:
            log.error("no server is reachable")
            return
        self.state.idle_seconds = 0
        open_steam_url(url)

    def _server_url(self) -> str | None:
        """Pick a server and return its ``steam://connect`` URL."""
        server = choose_server(self.servers, _query_server)
        if server is None:
            # Better to try the first configured server than to stall silently.
            server = first_or_none(self.servers)
        return server.connect_url() if server else None

    # --- shutdown ---------------------------------------------------------

    def shutdown(self) -> None:
        """Close the game and Steam, then let :meth:`run` fall out of its loop."""
        self.state.stopping.set()
        self.client.send(protocol.BYE)
        killed = kill_processes(_OWNED_PROCESSES)
        log.info("stopped %s process(es)", killed)
        self.client.close()


def _query_server(server: GameServer) -> ServerLoad | None:
    """A2S query for one server; ``None`` when it does not answer."""
    try:
        import a2s  # noqa: PLC0415 - optional dependency
    except ImportError:  # pragma: no cover - depends on the environment
        return None

    try:
        info = a2s.info(server.address, timeout=5)
    except Exception:  # noqa: BLE001 - any network failure means "no answer"
        return None
    return ServerLoad(players=info.player_count, slots=info.max_players)


def _pump(runner: Runner) -> None:
    """Feed panel messages to the runner until the connection closes."""
    for message in runner.client.messages():
        runner.handle(message.verb, message.args)
    log.info("the panel disconnected")
    runner.state.stopping.set()


def build_parser() -> argparse.ArgumentParser:
    """Command-line interface of the runner."""
    parser = argparse.ArgumentParser(
        prog="commendbot-runner",
        description="Drive one Steam account's CS:GO client for the panel.",
    )
    parser.add_argument("--steam-path", required=True, type=Path)
    parser.add_argument("--csgo-path", required=True, type=Path)
    parser.add_argument("--steam-id", required=True, type=int)
    parser.add_argument("--launch-arguments", default="")
    parser.add_argument(
        "--window-x", type=int, default=0, help="horizontal offset for tiling"
    )
    parser.add_argument(
        "--payload",
        type=Path,
        default=None,
        help="directory holding the local/userdata/game config payload",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    args = build_parser().parse_args(argv)

    token = os.environ.get(ENV_IPC_TOKEN, "").strip()
    if not token:
        log.error("%s is not set; the panel must start this process", ENV_IPC_TOKEN)
        return 2

    servers_file = os.environ.get(ENV_SERVERS_FILE, "").strip()
    servers = load_servers(Path(servers_file)) if servers_file else ()
    if not servers:
        log.warning("no server pool configured; only panel-driven connects will work")

    installation = launcher.Installation(args.steam_path, args.csgo_path)
    overrides = {k: v for k, v in (("host", args.host), ("port", args.port)) if v}
    client = ControlClient(token, args.steam_id, **overrides)

    try:
        client.connect()
    except (ConnectionError, RuntimeError) as exc:
        log.error("%s", exc)
        return 1

    runner = Runner(
        client,
        installation,
        args.steam_id,
        servers,
        launch_arguments=args.launch_arguments,
        payload_root=args.payload,
    )

    try:
        runner.prepare()
    except OSError as exc:
        log.error("could not prepare the game directory: %s", exc)
        runner.shutdown()
        return 1

    threading.Thread(target=_pump, args=(runner,), name="panel", daemon=True).start()

    try:
        runner.run()
    except KeyboardInterrupt:
        log.info("interrupted")
    finally:
        runner.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
