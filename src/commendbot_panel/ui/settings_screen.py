"""Paths, launch options and the two automation switches.

The bug that used to live here: the Auto-Start branch declared ``global
auto_start`` and then assigned to ``auto_reconnect`` instead, so toggling
Auto-Start changed the wrong setting and its own value never reached the
running process (AUDIT.md A2). Settings are now one immutable object that is
replaced as a whole, which makes that class of mistake impossible.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..config import UserSettings
from ..constants import DEFAULT_LAUNCH_ARGUMENTS
from ..ipc import protocol
from .simple_screens import Screen

END_TASK_CHOICES = ("Do nothing", "Turn off PC", "Close CS:GO", "Close Panel & CS:GO")


class SettingsScreen(Screen):
    """Edits :class:`~commendbot_panel.config.UserSettings`."""

    def build(self) -> None:
        ctk.CTkLabel(self.frame, text="Settings", font=("Roboto", 24, "bold")).pack(
            anchor="nw"
        )

        body = ctk.CTkFrame(self.frame)
        body.pack(fill="both", expand=True, pady=(15, 0))

        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=15, pady=15)

        self._steam_indicator = self._path_row(
            left, "Steam folder", "steam_path", self.app.settings.user.steam_path
        )
        self._csgo_indicator = self._path_row(
            left, "CS:GO folder", "csgo_path", self.app.settings.user.csgo_path
        )

        # Launch options -----------------------------------------------
        arguments = ctk.CTkFrame(left)
        arguments.pack(fill="x", pady=(12, 5))
        ctk.CTkLabel(arguments, text="Launch options", font=("Roboto", 13)).pack(
            anchor="nw"
        )
        self._arguments = ctk.CTkEntry(arguments, width=380)
        self._arguments.insert(0, self.app.settings.user.launch_arguments)
        self._arguments.pack(fill="x", pady=(2, 4))
        self._arguments.bind("<FocusOut>", lambda _e: self._save_arguments())
        ctk.CTkButton(
            arguments, text="Reset to defaults", width=140, command=self._reset_arguments
        ).pack(anchor="nw")

        # Switches -----------------------------------------------------
        switches = ctk.CTkFrame(left)
        switches.pack(fill="x", pady=10)

        self._auto_reconnect = ctk.CTkCheckBox(
            switches,
            text="Auto-Reconnect",
            command=self._toggle_auto_reconnect,
            checkbox_width=20,
            checkbox_height=20,
            font=("Roboto", 13),
        )
        self._auto_reconnect.pack(anchor="w", pady=(0, 2))

        self._auto_start = ctk.CTkCheckBox(
            switches,
            text="Auto-Start",
            command=self._toggle_auto_start,
            checkbox_width=20,
            checkbox_height=20,
            font=("Roboto", 13),
        )
        self._auto_start.pack(anchor="w", pady=(2, 0))

        # When the runners do not reconnect on their own there is nothing for
        # auto-start to hang off, so the second switch follows the first.
        self._sync_switches()

        # What to do when a job finishes -------------------------------
        finish = ctk.CTkFrame(left)
        finish.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(finish, text="When commending finishes", font=("Roboto", 13)).pack(
            anchor="nw"
        )
        self._end_task = ctk.CTkOptionMenu(
            finish,
            values=list(END_TASK_CHOICES),
            command=self._set_end_task,
            dynamic_resizing=False,
        )
        self._end_task.set(self.app.settings.user.end_task)
        self._end_task.pack(anchor="nw", pady=2)

    # --- path rows --------------------------------------------------------

    def _path_row(
        self, master: ctk.CTkBaseClass, caption: str, field: str, value: Path | None
    ) -> ctk.CTkLabel:
        """A caption, a status dot and a browse button. Returns the dot."""
        row = ctk.CTkFrame(master, fg_color="#353639")
        row.pack(fill="x", pady=4)

        indicator = ctk.CTkLabel(row, text=self._dot(value), width=16)
        indicator.pack(side="left", padx=(10, 4))

        ctk.CTkButton(
            row,
            text=caption,
            width=140,
            fg_color="transparent",
            hover=False,
            command=lambda: self._browse(field, indicator),
        ).pack(side="left")

        self._path_label(row, value)
        return indicator

    @staticmethod
    def _path_label(master: ctk.CTkBaseClass, value: Path | None) -> None:
        """Show the configured path, or a hint when there is none."""
        ctk.CTkLabel(
            master,
            text=str(value) if value else "not set",
            font=("Roboto", 10),
            anchor="w",
        ).pack(side="left", padx=8, fill="x", expand=True)

    @staticmethod
    def _dot(value: Path | None) -> str:
        """Green when the directory exists, red otherwise."""
        return "🟢" if value and value.is_dir() else "🔴"

    def _browse(self, field: str, indicator: ctk.CTkLabel) -> None:
        """Ask for a directory and store it if the user picked one."""
        chosen = filedialog.askdirectory(mustexist=True)
        if not chosen:
            return
        path = Path(chosen)
        self._update(**{field: path})
        indicator.configure(text=self._dot(path))

    # --- individual settings ---------------------------------------------

    def _save_arguments(self) -> None:
        text = self._arguments.get().strip()
        self._update(launch_arguments=text or DEFAULT_LAUNCH_ARGUMENTS)

    def _reset_arguments(self) -> None:
        self._arguments.delete(0, "end")
        self._arguments.insert(0, DEFAULT_LAUNCH_ARGUMENTS)
        self._update(launch_arguments=DEFAULT_LAUNCH_ARGUMENTS)

    def _toggle_auto_reconnect(self) -> None:
        enabled = bool(self._auto_reconnect.get())
        self._update(auto_reconnect=enabled)
        self._sync_switches()
        # Tell every runner immediately; they act on it on their next poll.
        self.app.control_server.broadcast(
            protocol.SETTINGS, f"autoreconnect={int(enabled)}"
        )

    def _toggle_auto_start(self) -> None:
        self._update(auto_start=bool(self._auto_start.get()))

    def _set_end_task(self, choice: str) -> None:
        self._update(end_task=choice)

    def _sync_switches(self) -> None:
        """Reflect the stored values and gate Auto-Start on Auto-Reconnect."""
        user = self.app.settings.user
        (self._auto_reconnect.select if user.auto_reconnect else self._auto_reconnect.deselect)()
        (self._auto_start.select if user.auto_start else self._auto_start.deselect)()
        self._auto_start.configure(
            state="normal" if user.auto_reconnect else "disabled"
        )

    def _update(self, **changes) -> None:
        """Write one or more fields through to the app and the settings store."""
        updated: UserSettings = replace(self.app.settings.user, **changes)
        self.app.update_user_settings(updated)
