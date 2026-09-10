"""The application shell: window, navigation, background threads.

Threading rule for the whole package: **only this class touches widgets.**
Anything that runs off the main thread — the control server, the change-stream
watcher, the login lookup, a bulk import — calls :meth:`PanelApp.call_on_ui`,
which hands the work back through Tk's own event queue. The original updated
labels straight from three different threads, which is undefined behaviour in
Tk and one of the likelier explanations for its random crashes (AUDIT.md B9).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from .. import __version__
from ..config import (
    ENV_IPC_TOKEN,
    Settings,
    SettingsStore,
    UserSettings,
    default_store,
)
from ..constants import (
    STATUS_DONE,
    STATUS_ERROR,
    WINDOW_TILE_STEP,
)
from ..database import Database, DatabaseError
from ..ipc import protocol
from ..ipc.server import AddressInUseError, ControlServer, RunnerConnection
from ..steam import launcher, loginusers
from ..steam.guard import GuardError, generate_two_factor_code
from ..windows import (
    CREATE_NEW_CONSOLE,
    CREATE_NO_WINDOW,
    ForegroundError,
    bring_to_front,
    machine_id,
)
from .commend_screen import CommendScreen
from .login import LoginWindow
from .settings_screen import SettingsScreen
from .simple_screens import BalanceScreen, HomeScreen
from .widgets import AssetLoader, NavButton

log = logging.getLogger(__name__)

# How often the panel re-reads the database for the screen it is showing.
_REFRESH_MS = 10_000

ASSET_DIRECTORY = Path(__file__).resolve().parents[3] / "assets" / "images"


class PanelApp(ctk.CTk):
    """The main window."""

    def __init__(self, settings: Settings, store: SettingsStore | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.store = store or default_store()
        self.assets = AssetLoader(ASSET_DIRECTORY)
        self.hwid = machine_id()

        self.database: Database | None = None
        self.user: dict[str, Any] | None = None
        self.screens: dict[str, Any] = {}
        self.nav_buttons: dict[str, NavButton] = {}

        # Credentials for accounts whose runner has not connected yet, and the
        # Steam Guard secrets they were started with.
        self._pending_credentials: dict[int, tuple[str, str]] = {}
        self._guard_secrets: dict[int, str] = {}
        self._window_offset = 0
        self._shutting_down = threading.Event()

        self.control_server = ControlServer(settings.ipc_token, self._on_runner_message)

        self._configure_window()
        self._start_control_server()

        # Nothing else is built until somebody signs in.
        self.withdraw()
        self.login_window = LoginWindow(self, self._on_signed_in)

    # --- window -----------------------------------------------------------

    def _configure_window(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.title(f"CommendBot Panel {__version__}")
        self.resizable(width=False, height=False)

        width, height = 780, 470
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

        icon = self.assets.icon_path("test.ico")
        if icon:
            self.iconbitmap(icon)

        self.protocol("WM_DELETE_WINDOW", self.quit_application)

    def _start_control_server(self) -> None:
        """Bind the loopback port, or refuse to run as a second instance."""
        try:
            self.control_server.start()
        except AddressInUseError as exc:
            messagebox.showerror("Already running", str(exc))
            self.destroy()
            raise SystemExit(1) from exc

    # --- thread marshalling ----------------------------------------------

    def call_on_ui(self, function, *args) -> None:
        """Run ``function(*args)`` on the Tk thread.

        Safe to call from anywhere. After the window is gone the call is
        dropped, which is what should happen during shutdown.
        """
        try:
            self.after(0, lambda: function(*args))
        except RuntimeError:
            log.debug("dropping a UI call after shutdown")

    # --- sign-in and layout ----------------------------------------------

    def ensure_database(self) -> Database:
        """Open the connection on first use.

        Raises:
            DatabaseError: if the cluster cannot be reached.
        """
        if self.database is None:
            self.database = Database.connect(self.settings.mongo_uri)
        return self.database

    def remember_login(self, login: str) -> None:
        """Store the login name so the next start pre-fills it."""
        self.update_user_settings(replace(self.settings.user, remembered_login=login))

    def _on_signed_in(self, user: dict[str, Any]) -> None:
        """Build the panel proper once the credentials check out."""
        self.user = user
        self._build_layout()
        self.deiconify()

        threading.Thread(
            target=self._watch_database, name="change-stream", daemon=True
        ).start()
        self.after(_REFRESH_MS, self._periodic_refresh)

    def _build_layout(self) -> None:
        """The navigation rail plus one frame per screen."""
        rail = ctk.CTkFrame(self, width=60)
        rail.pack(fill="y", side="left")

        logo = self.assets.icon("logo.png", 40)
        if logo:
            ctk.CTkButton(
                rail,
                text="",
                image=logo,
                fg_color="transparent",
                hover=False,
                width=40,
                height=40,
            ).pack(pady=(10, 20))

        self.screens = {
            "home": HomeScreen(self),
            "commend": CommendScreen(self),
            "balance": BalanceScreen(self),
            "settings": SettingsScreen(self),
        }

        entries = (
            ("home", "home", "Home"),
            ("commend", "smile", "Run"),
            ("balance", "money_bag", "Cash"),
            ("settings", "settings", "Setup"),
        )
        for key, stem, fallback in entries:
            button = NavButton(
                rail,
                active_icon=self.assets.icon(f"{stem}-white.png"),
                inactive_icon=self.assets.icon(f"{stem}-gray.png"),
                fallback_text=fallback,
                command=lambda k=key: self.show_screen(k),
            )
            button.pack(pady=8, padx=12)
            self.nav_buttons[key] = button

        ctk.CTkLabel(rail, text=f"v{__version__}", font=("Roboto", 8)).pack(
            side="bottom", pady=6
        )
        self.show_screen("home")

    def show_screen(self, key: str) -> None:
        """Bring one screen forward and mark its nav button active."""
        for name, screen in self.screens.items():
            if name == key:
                screen.show()
            else:
                screen.hide()
        for name, button in self.nav_buttons.items():
            button.set_active(name == key)

    def update_user_settings(self, user: UserSettings) -> None:
        """Persist changed preferences and keep the in-memory copy in step."""
        self.settings = self.settings.with_user(user)
        try:
            self.store.save(user)
        except OSError as exc:
            log.warning("could not save settings: %s", exc)

    @property
    def installation(self) -> launcher.Installation | None:
        """Steam and CS:GO locations, or ``None`` while they are unconfigured."""
        user = self.settings.user
        if not user.paths_are_valid:
            return None
        return launcher.Installation(user.steam_path, user.csgo_path)

    # --- Steam accounts ---------------------------------------------------

    def resolve_local_account(self, account: str) -> int | None:
        """SteamID64 for an account Steam has already signed in here."""
        install = self.installation
        if install is None:
            return None
        vdf_path = loginusers.login_users_path(install.steam_path)
        try:
            text = vdf_path.read_text(encoding="utf-8")
        except OSError:
            return None
        return loginusers.find_steam_id_by_account(text, account)

    def sign_in_once(self, account: str, password: str) -> None:
        """Start Steam so it registers an account we have never seen."""
        install = self.installation
        if install is None:
            return
        launcher.spawn(
            launcher.build_steam_login_command(install, account, password),
            creationflags=CREATE_NO_WINDOW,
        )

    def launch_runner(
        self,
        steam_id64: int,
        account: str,
        password: str,
        shared_secret: str | None = None,
    ) -> None:
        """Start the runner process for one account.

        The credentials are held here and sent over the control channel once
        the runner has authenticated, so they never appear on its command line
        (AUDIT.md B1).
        """
        install = self.installation
        if install is None:
            self.call_on_ui(
                messagebox.showerror,
                "Set the paths first",
                "Configure the Steam and CS:GO folders in Settings.",
            )
            return

        self._pending_credentials[steam_id64] = (account, password)
        if shared_secret:
            self._guard_secrets[steam_id64] = shared_secret

        command = launcher.build_runner_command(
            _runner_command(),
            install,
            steam_id64,
            window_offset=self._window_offset,
            launch_arguments=self.settings.user.launch_arguments,
        )
        self._window_offset += WINDOW_TILE_STEP

        # The token is generated in this process, so it has to be handed to the
        # child explicitly — inheriting our environment is not enough.
        environment = {**os.environ, ENV_IPC_TOKEN: self.settings.ipc_token}

        launcher.spawn(command, creationflags=CREATE_NEW_CONSOLE, env=environment)
        log.info("runner launched for %s", steam_id64)

    # --- messages from the runners ---------------------------------------

    def _on_runner_message(
        self, connection: RunnerConnection, message: protocol.Message
    ) -> None:
        """Runs on the runner's own thread; only queues work for the UI."""
        steam_id = connection.steam_id64

        if message.verb == protocol.HELLO:
            connection.send(
                protocol.SETTINGS,
                f"autoreconnect={int(self.settings.user.auto_reconnect)}",
            )
            credentials = self._pending_credentials.pop(steam_id, None)
            if credentials:
                connection.send(protocol.CREDENTIALS, *credentials)

        elif message.verb == protocol.STARTED:
            self.call_on_ui(self._log_activity, f"{steam_id} is on a server")
            if self.settings.user.auto_start:
                self.call_on_ui(self._auto_start_job, steam_id)

        elif message.verb == protocol.LOGIN_WINDOW:
            self._type_guard_code(connection, message.arg(0))

        elif message.verb == protocol.BYE:
            self.call_on_ui(self._log_activity, f"{steam_id} stopped")

    def _type_guard_code(self, connection: RunnerConnection, raw_hwnd: str) -> None:
        """Focus the Steam Guard window and type the current code into it."""
        secret = self._guard_secrets.get(connection.steam_id64)
        if not secret or not raw_hwnd.isdigit():
            return

        try:
            code = generate_two_factor_code(secret)
        except GuardError as exc:
            log.warning("no Steam Guard code for %s: %s", connection.steam_id64, exc)
            return

        try:
            bring_to_front(int(raw_hwnd))
        except ForegroundError:
            # The window went away; ask the runner to look again.
            connection.send(protocol.FIND_LOGIN)
            return

        try:
            import pyautogui  # noqa: PLC0415 - optional dependency
        except ImportError:  # pragma: no cover - depends on the environment
            log.warning("pyautogui is not installed; type the code by hand")
            return

        pyautogui.write(code)
        pyautogui.press("enter")

    def _auto_start_job(self, steam_id64: int) -> None:
        """Queue the backend "start" command for a job that just connected."""
        if self.database is None:
            return
        raw = self.database.server_users.find_one({"steamID64": steam_id64})
        if raw is not None:
            self.database.queue_command(raw, self.hwid, "start")

    # --- database change stream -------------------------------------------

    def _watch_database(self) -> None:
        """Follow the shared database and mirror the changes onto the screen.

        A loop, not recursion. The original called itself after every dropped
        cursor, so the stack grew for the lifetime of the session
        (AUDIT.md A12).
        """
        while True:
            try:
                database = self.ensure_database()
                for change in database.watch_jobs():
                    self._handle_change(change)
            except DatabaseError as exc:
                log.warning("change stream unavailable: %s", exc)
            except Exception:
                log.info("change stream dropped, reopening")

            # Wait before reopening, and stop entirely once we are shutting down.
            if self._shutting_down.wait(2.0):
                return

    def _handle_change(self, change: dict[str, Any]) -> None:
        """Translate one change-stream event into a screen update."""
        collection = change.get("ns", {}).get("coll")
        if collection != "serverusers":
            return

        document = change.get("fullDocument") or {}
        steam_id = document.get("steamID64") or change.get("documentKey", {}).get("_id")
        status = document.get("status")

        if status == STATUS_ERROR:
            reason = document.get("reason", "unknown reason")
            self.call_on_ui(
                messagebox.showerror,
                "Commending failed",
                f"Account {steam_id} could not be started.\nReason: {reason}",
            )
        elif status == STATUS_DONE:
            received = document.get("actualamount", 0)
            total = document.get("amount", 0)
            self.call_on_ui(self._log_activity, f"{steam_id} finished {received}/{total}")
            self.call_on_ui(self._run_end_task, steam_id)

        self.call_on_ui(self._refresh_current_screen)

    def _run_end_task(self, steam_id64: int) -> None:
        """Honour the "when commending finishes" preference."""
        choice = self.settings.user.end_task
        if choice == "Turn off PC":
            import os  # noqa: PLC0415 - only needed on this path

            os.system("shutdown /s /t 60")
        elif choice in ("Close CS:GO", "Close Panel & CS:GO"):
            self.control_server.send_to(steam_id64, protocol.CLOSE)
            if choice == "Close Panel & CS:GO" and not self.control_server.steam_ids:
                self.quit_application()

    # --- periodic work ----------------------------------------------------

    def _periodic_refresh(self) -> None:
        """Re-read the visible screen every few seconds."""
        self._refresh_current_screen()
        self.after(_REFRESH_MS, self._periodic_refresh)

    def _refresh_current_screen(self) -> None:
        for name, screen in self.screens.items():
            if self.nav_buttons.get(name) and screen.frame.winfo_ismapped():
                screen.refresh()

    def _log_activity(self, text: str) -> None:
        """Append a line to the commend screen's activity strip."""
        screen = self.screens.get("commend")
        if screen is not None:
            screen.add_log(text)

    # --- shutdown and crash reporting ------------------------------------

    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        """Tk calls this for any exception raised inside a callback."""
        message = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        log.error("unhandled UI error\n%s", message)
        messagebox.showerror("Error", message)
        if self.database is not None:
            self.database.log_error(self.hwid, message, __version__)

    def quit_application(self) -> None:
        """Close everything in order: runners, sockets, database, window."""
        log.info("shutting down")
        self._shutting_down.set()
        self.control_server.broadcast(protocol.CLOSE)
        self.control_server.stop()
        if self.database is not None:
            self.database.close()
        self.destroy()


def _runner_command() -> list[str]:
    """How to invoke the runner on this installation.

    A frozen build ships ``commendbot-runner.exe`` next to the panel; a source
    checkout re-uses the current interpreter.
    """
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).with_name("commendbot-runner.exe"))]
    return [sys.executable, "-m", "commendbot_panel.runner"]
