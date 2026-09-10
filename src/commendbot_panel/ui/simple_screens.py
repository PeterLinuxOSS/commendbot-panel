"""The two screens that carry almost no logic.

Both were empty frames in the original — the navigation buttons existed and led
nowhere. They are kept, with the balance screen now at least showing what the
signed-in account actually has, because removing navigation entries would
change the shape of the app rather than clean it up.
"""

from __future__ import annotations

import customtkinter as ctk

from .. import __version__


class Screen:
    """Common behaviour for a page of the panel.

    A screen owns one frame. ``show`` and ``hide`` only manage geometry, so
    switching pages never rebuilds the widgets.
    """

    def __init__(self, app) -> None:
        self.app = app
        self.frame = ctk.CTkFrame(app)
        self.build()

    def build(self) -> None:
        """Create the widgets. Called once, from ``__init__``."""

    def show(self) -> None:
        """Make the screen visible."""
        self.frame.pack(fill="both", expand=True, padx=20, pady=15)

    def hide(self) -> None:
        """Take the screen out of the layout without destroying it."""
        self.frame.pack_forget()

    def refresh(self) -> None:
        """Re-read anything that may have changed. Called on a timer."""


class HomeScreen(Screen):
    """Landing page: what this build is and where the operator is signed in."""

    def build(self) -> None:
        ctk.CTkLabel(
            self.frame, text="CommendBot Panel", font=("Roboto", 24, "bold")
        ).pack(anchor="nw")
        ctk.CTkLabel(self.frame, text=f"Version {__version__}", font=("Roboto", 12)).pack(
            anchor="nw", pady=(0, 15)
        )

        self._account = ctk.CTkLabel(self.frame, text="", font=("Roboto", 13))
        self._account.pack(anchor="nw")
        self._machine = ctk.CTkLabel(self.frame, text="", font=("Roboto", 11))
        self._machine.pack(anchor="nw", pady=(4, 0))
        self.refresh()

    def refresh(self) -> None:
        user = self.app.user or {}
        self._account.configure(text=f"Signed in as {user.get('login', '—')}")
        self._machine.configure(text=f"Machine ID {self.app.hwid}")


class BalanceScreen(Screen):
    """Remaining commends per slot for the signed-in account."""

    def build(self) -> None:
        ctk.CTkLabel(self.frame, text="Balance", font=("Roboto", 24, "bold")).pack(
            anchor="nw", pady=(0, 12)
        )
        self._body = ctk.CTkFrame(self.frame, fg_color="transparent")
        self._body.pack(fill="both", expand=True)
        self._rows: list[ctk.CTkBaseClass] = []

    def show(self) -> None:
        super().show()
        self.refresh()

    def refresh(self) -> None:
        """Redraw one row per slot. Cheap enough to rebuild wholesale."""
        for row in self._rows:
            row.destroy()
        self._rows.clear()

        database = self.app.database
        if database is None or self.app.user is None:
            self._add_row("Not connected.")
            return

        user_id = int(self.app.user["userid"])
        try:
            slots = database.list_slots()
        except Exception:  # noqa: BLE001 - a dead cluster must not kill the screen
            self._add_row("Cannot reach the server.")
            return

        if not slots:
            self._add_row("No slots are configured.")
            return

        for slot in slots:
            balance = database.get_balance(user_id, slot.id)
            amount = balance.amount if balance else 0
            used = balance.today_used if balance else 0
            self._add_row(f"{slot.label}: {amount} left, {used} used today")

    def _add_row(self, text: str) -> None:
        label = ctk.CTkLabel(self._body, text=text, font=("Roboto", 13))
        label.pack(anchor="nw", pady=2)
        self._rows.append(label)
