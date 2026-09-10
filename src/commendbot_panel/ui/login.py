"""The sign-in window.

Two changes worth knowing about:

* only the login name is remembered between sessions. The original wrote the
  password into the registry in clear text and rewrote it on every sign-in
  (AUDIT.md B5).
* the database is queried on a worker thread, so a slow or unreachable cluster
  no longer freezes the window for the whole connect timeout.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import customtkinter as ctk

from ..database import Database, DatabaseError

log = logging.getLogger(__name__)

# Called with the authenticated user document once sign-in succeeds.
OnSuccess = Callable[[dict[str, Any]], None]


class LoginWindow(ctk.CTkToplevel):
    """Modal-ish window shown before the panel itself."""

    def __init__(self, app, on_success: OnSuccess) -> None:
        super().__init__(app)
        self.app = app
        self._on_success = on_success
        self._busy = False

        self.title("CommendBot Panel")
        self.resizable(width=False, height=False)
        self._centre(320, 350)
        icon = app.assets.icon_path("test.ico")
        if icon:
            self.iconbitmap(icon)
        self.protocol("WM_DELETE_WINDOW", self.app.quit_application)

        frame = ctk.CTkFrame(self)
        frame.pack(fill="both", expand=True)

        ctk.CTkLabel(frame, text="CommendBot", font=("Roboto", 20, "bold")).pack(
            pady=10, padx=12
        )

        self.login_entry = ctk.CTkEntry(frame, placeholder_text="Login")
        self.login_entry.pack(pady=10, padx=12)
        self.login_entry.insert(0, app.settings.user.remembered_login)

        self.password_entry = ctk.CTkEntry(frame, placeholder_text="Password", show="*")
        self.password_entry.pack(pady=5, padx=6)
        self.password_entry.bind("<Return>", lambda _event: self.submit())

        self.error_label = ctk.CTkLabel(frame, text="")
        self.error_label.pack()

        self.submit_button = ctk.CTkButton(frame, text="Login", command=self.submit)
        self.submit_button.pack()

        self.after(100, self.login_entry.focus_set)

    def _centre(self, width: int, height: int) -> None:
        """Place the window in the middle of the screen."""
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    # --- sign-in ----------------------------------------------------------

    def submit(self) -> None:
        """Validate the fields and start the lookup on a worker thread."""
        if self._busy:
            return

        login = self.login_entry.get().strip()
        password = self.password_entry.get()
        if not login or not password:
            self._show_error("Enter a username and a password.")
            return

        self._set_busy(True)
        self._show_error("")
        threading.Thread(
            target=self._authenticate,
            args=(login, password),
            name="login",
            daemon=True,
        ).start()

    def _authenticate(self, login: str, password: str) -> None:
        """Runs off the UI thread; every result is marshalled back with after()."""
        try:
            database = self.app.ensure_database()
            user = database.find_user(login, password)
        except DatabaseError as exc:
            log.warning("sign-in failed: %s", exc)
            self.app.call_on_ui(self._finish_error, "Cannot reach the server.")
            return

        if not user:
            self.app.call_on_ui(self._finish_error, "Wrong username or password.")
            return

        problem = self._check_account(database, user)
        if problem:
            self.app.call_on_ui(self._finish_error, problem)
            return

        self.app.call_on_ui(self._finish_success, login, user)

    def _check_account(self, database: Database, user: dict[str, Any]) -> str | None:
        """Blacklist and machine-binding rules. Returns the refusal, or ``None``."""
        user_id = int(user["userid"])
        if database.is_user_blacklisted(user_id):
            return "This account is blacklisted."

        bound = user.get("hwid")
        if not bound:
            # First sign-in on any machine claims the licence for this one.
            database.bind_machine(user["_id"], self.app.hwid)
            return None
        if bound != self.app.hwid:
            return "This licence is linked to another PC."
        return None

    # --- UI-thread callbacks ---------------------------------------------

    def _finish_error(self, message: str) -> None:
        self._set_busy(False)
        self._show_error(message)

    def _finish_success(self, login: str, user: dict[str, Any]) -> None:
        self.app.remember_login(login)
        self.destroy()
        self._on_success(user)

    def _show_error(self, message: str) -> None:
        self.error_label.configure(text=message, text_color="red")

    def _set_busy(self, busy: bool) -> None:
        """Disable the button while a lookup is in flight."""
        self._busy = busy
        self.submit_button.configure(
            state="disabled" if busy else "normal",
            text="Checking…" if busy else "Login",
        )
