"""The working screen: place orders, watch them run.

Two ways in. *Link* commends somebody else's profile and needs nothing but a
profile URL. *Login* commends an account whose credentials the operator has,
which means signing Steam in and starting a runner for it.

Both paths used to be separate ~90-line ``if`` ladders that had drifted apart.
They now share :func:`commendbot_panel.jobs.validate_order` and differ only in
how the target is identified and whether a runner is launched.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..constants import (
    STATUS_CONFIRMED,
    STATUS_LABELS,
    STATUS_STOPPED,
    STATUS_WAITING_CONNECT,
)
from ..database import JobRecord
from ..jobs import (
    Balance,
    Order,
    Slot,
    describe,
    parse_bulk_file,
    parse_slot_label,
    validate_order,
)
from ..steam.ids import parse_steam_id
from .simple_screens import Screen
from .widgets import ScrollableFrame, StatTile

log = logging.getLogger(__name__)


class CommendScreen(Screen):
    """Order entry, live statistics and the log strip."""

    def build(self) -> None:
        self.slots: list[Slot] = []
        self.selected_account: int | None = None

        top = ctk.CTkFrame(self.frame, fg_color="transparent")
        top.pack(fill="x", side="top")

        self._build_order_tabs(top)
        self._build_log_panel(top)
        self._build_stats_panel()

        self.reload_slots()

    # --- construction -----------------------------------------------------

    def _build_order_tabs(self, master: ctk.CTkBaseClass) -> None:
        """The Link/Login tab pair on the left."""
        tabs = ctk.CTkTabview(master, width=230, height=230)
        tabs.pack(side="left", padx=(0, 20), pady=(0, 10))
        link = tabs.add("Link")
        login = tabs.add("Login")

        # Link tab -----------------------------------------------------
        self.link_profile = ctk.CTkEntry(
            link, placeholder_text="Profile link", width=200, justify="center"
        )
        self.link_profile.pack(padx=5, pady=5)
        self.link_amount = ctk.CTkEntry(
            link, placeholder_text="Number of commends", width=170, justify="center"
        )
        self.link_amount.pack(padx=5, pady=5)
        self.link_slot = ctk.CTkOptionMenu(link, values=["—"])
        self.link_slot.pack(padx=5, pady=5)
        self.link_error = ctk.CTkLabel(
            link, text="", text_color="red", font=("Roboto", 11), wraplength=200
        )
        self.link_error.pack(padx=5)
        ctk.CTkButton(link, text="Start", command=self.start_link_job).pack(pady=(8, 5))

        # Login tab ----------------------------------------------------
        self.login_account = ctk.CTkEntry(
            login, placeholder_text="Steam login", width=200, justify="center"
        )
        self.login_account.pack(padx=5, pady=(0, 5))
        self.login_password = ctk.CTkEntry(
            login, placeholder_text="Password", width=200, justify="center", show="*"
        )
        self.login_password.pack(padx=5)
        self.login_amount = ctk.CTkEntry(
            login, placeholder_text="Number of commends", width=170, justify="center"
        )
        self.login_amount.pack(padx=5, pady=5)
        self.login_slot = ctk.CTkOptionMenu(login, values=["—"])
        self.login_slot.pack(padx=5)
        self.login_error = ctk.CTkLabel(
            login, text="", text_color="red", font=("Roboto", 11), wraplength=200
        )
        self.login_error.pack(padx=5)

        buttons = ctk.CTkFrame(login, fg_color="transparent")
        buttons.pack(pady=5)
        ctk.CTkButton(buttons, text="Start", width=90, command=self.start_login_job).pack(
            side="left", padx=2
        )
        ctk.CTkButton(buttons, text="Import…", width=90, command=self.import_bulk).pack(
            side="left", padx=2
        )

    def _build_log_panel(self, master: ctk.CTkBaseClass) -> None:
        """The activity strip on the right."""
        panel = ctk.CTkFrame(master)
        panel.pack(side="right", fill="both", expand=True, pady=(0, 10))
        ctk.CTkLabel(panel, text="Activity", font=("Roboto", 15, "bold")).pack(
            anchor="nw", padx=15, pady=(8, 0)
        )
        self.log_list = ScrollableFrame(panel, width=380, height=170)
        self.log_list.pack(fill="both", expand=True, padx=10, pady=10)
        self._log_rows: list[ctk.CTkLabel] = []

    def _build_stats_panel(self) -> None:
        """Account picker, the two action buttons and six stat tiles."""
        panel = ctk.CTkFrame(self.frame)
        panel.pack(fill="x", side="bottom")

        controls = ctk.CTkFrame(panel, fg_color="transparent")
        controls.pack(side="left", padx=15, pady=15)

        self.account_picker = ctk.CTkOptionMenu(
            controls, values=[" "], command=self.select_account
        )
        self.account_picker.pack(pady=(0, 10))

        self.stop_button = ctk.CTkButton(
            controls, text="Stop", state="disabled", command=self.on_stop
        )
        self.stop_button.pack(pady=5)
        self.pause_button = ctk.CTkButton(
            controls, text="Pause", state="disabled", command=self.on_pause
        )
        self.pause_button.pack(pady=5)

        tiles = ctk.CTkFrame(panel, fg_color="transparent")
        tiles.pack(side="right", padx=15, pady=15)

        row_one = ctk.CTkFrame(tiles, fg_color="transparent")
        row_one.pack()
        row_two = ctk.CTkFrame(tiles, fg_color="transparent")
        row_two.pack(pady=(10, 0))

        self.tile_received = StatTile(row_one, "Received")
        self.tile_pending = StatTile(row_one, "Pending")
        self.tile_total = StatTile(row_one, "Total")
        self.tile_status = StatTile(row_two, "Status", "Free")
        self.tile_chunk = StatTile(row_two, "Chunk", "#0・[0/0]")
        self.tile_eta = StatTile(row_two, "End time", "0 min")

        for tile in (self.tile_received, self.tile_pending, self.tile_total):
            tile.pack(side="left", padx=12)
        for tile in (self.tile_status, self.tile_chunk, self.tile_eta):
            tile.pack(side="left", padx=12)

    # --- data -------------------------------------------------------------

    def show(self) -> None:
        super().show()
        self.refresh()

    def reload_slots(self) -> None:
        """Re-read the slot list and repopulate both drop-downs."""
        database = self.app.database
        if database is None:
            return
        try:
            self.slots = database.list_slots()
        except Exception:  # noqa: BLE001 - a dead cluster leaves the old list up
            log.warning("could not read the slot list")
            return

        labels = [slot.label for slot in self.slots] or ["—"]
        for menu in (self.link_slot, self.login_slot):
            menu.configure(values=labels)
            if menu.get() not in labels:
                menu.set(labels[0])

    def refresh(self) -> None:
        """Redraw the account picker and the tiles from the database."""
        database = self.app.database
        if database is None:
            return

        try:
            jobs = database.list_active_jobs(self.app.hwid)
        except Exception:  # noqa: BLE001 - keep the last known state on screen
            return

        ids = [str(job.steam_id64) for job in jobs]
        self.account_picker.configure(values=ids or [" "])

        if self.selected_account is None or str(self.selected_account) not in ids:
            self.selected_account = jobs[0].steam_id64 if jobs else None
            self.account_picker.set(ids[0] if ids else " ")

        current = next(
            (job for job in jobs if job.steam_id64 == self.selected_account), None
        )
        self.show_job(current)

    def select_account(self, value: str) -> None:
        """Drop-down callback."""
        self.selected_account = int(value) if value.strip().isdigit() else None
        self.refresh()

    def show_job(self, job: JobRecord | None) -> None:
        """Fill the tiles and set the two buttons for one job."""
        if job is None:
            self.tile_received.set("0")
            self.tile_pending.set("0")
            self.tile_total.set("0")
            self.tile_status.set("Free")
            self.tile_chunk.set("#0・[0/0]")
            self.tile_eta.set("0 min")
            self._set_buttons(stop="Stop", pause="Pause", enabled=False)
            return

        self.tile_received.set(str(job.received))
        self.tile_pending.set(str(job.pending))
        self.tile_total.set(str(job.amount))
        self.tile_status.set(STATUS_LABELS.get(job.status, job.status))
        self.tile_chunk.set(f"{job.chunk}・{job.chunk_info}")
        self.tile_eta.set(self._format_eta(job))

        # A command already queued for this account means the backend owns it.
        database = self.app.database
        queued = database.pending_command(job.steam_id64) if database else None
        if queued is not None:
            self._set_buttons(stop="Stop", pause="Pause", enabled=False)
        elif job.status == STATUS_CONFIRMED:
            self._set_buttons(stop="Stop", pause="Pause", enabled=True)
        elif job.status in (STATUS_WAITING_CONNECT, STATUS_STOPPED):
            self._set_buttons(stop="Confirm", pause="Cancel", enabled=True)
        else:
            self._set_buttons(stop="Stop", pause="Pause", enabled=False)

    @staticmethod
    def _format_eta(job: JobRecord) -> str:
        """Turn the stored end timestamp into ``x min`` or ``x hr``."""
        if not job.ends_at:
            return "0 min"

        import datetime as dt  # noqa: PLC0415 - only needed on this path

        end = dt.datetime.fromtimestamp(job.ends_at, tz=dt.timezone.utc)
        minutes = (end - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60
        if minutes <= 0:
            return "0 min"
        return f"{minutes / 60:.1f} hr" if minutes > 60 else f"{int(minutes)} min"

    def _set_buttons(self, *, stop: str, pause: str, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.stop_button.configure(text=stop, state=state)
        self.pause_button.configure(text=pause, state=state)

    # --- placing orders ---------------------------------------------------

    def start_link_job(self) -> None:
        """Commend a profile the operator does not have credentials for."""
        self.link_error.configure(text="")
        link = self.link_profile.get()
        steam_id = parse_steam_id(link)
        if steam_id is None:
            self.link_error.configure(text="That is not a Steam profile link.")
            return

        order = self._build_order(self.link_amount.get(), self.link_slot.get())
        if order is None:
            self.link_error.configure(text="Fill in the amount and pick a slot.")
            return
        order = Order(steam_id64=steam_id, amount=order.amount, slot=order.slot)

        problem = self._place(order)
        if problem:
            self.link_error.configure(text=problem)
            return

        self.link_profile.delete(0, "end")
        self.link_amount.delete(0, "end")
        self.refresh()

    def start_login_job(self) -> None:
        """Sign an account in locally and commend it."""
        self.login_error.configure(text="")
        account = self.login_account.get().strip()
        password = self.login_password.get()
        if not account or not password:
            self.login_error.configure(text="Enter the Steam login and password.")
            return

        order_shape = self._build_order(self.login_amount.get(), self.login_slot.get())
        if order_shape is None:
            self.login_error.configure(text="Fill in the amount and pick a slot.")
            return

        self.login_account.delete(0, "end")
        self.login_password.delete(0, "end")
        self.login_amount.delete(0, "end")

        threading.Thread(
            target=self._run_local_job,
            args=(account, password, order_shape.amount, order_shape.slot, None),
            name="local-job",
            daemon=True,
        ).start()

    def import_bulk(self) -> None:
        """Read a ``login:password:amount[:secret]`` file and run the lot."""
        if not self.app.installation:
            messagebox.showerror(
                "Set the paths first",
                "Configure the Steam and CS:GO folders in Settings.",
            )
            return

        chosen = filedialog.askopenfilename(
            title="Select an account list", filetypes=[("Text file", "*.txt")]
        )
        if not chosen:
            return

        try:
            entries = parse_bulk_file(Path(chosen).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Import failed", str(exc))
            return

        slot = self._slot_from_label(self.login_slot.get())
        if slot is None:
            messagebox.showerror("Import failed", "Pick a slot first.")
            return

        threading.Thread(
            target=self._run_bulk,
            args=(entries, slot),
            name="bulk-import",
            daemon=True,
        ).start()

    def _run_bulk(self, entries, slot: Slot) -> None:
        """Work through an import list one account at a time."""
        for entry in entries:
            failed = self._run_local_job(
                entry.login, entry.password, entry.amount, slot, entry.shared_secret
            )
            if failed:
                log.warning("stopping the import at %s", entry.login)
                return

    def _run_local_job(
        self,
        account: str,
        password: str,
        amount: int,
        slot: Slot,
        shared_secret: str | None,
    ) -> bool:
        """Validate, then hand the account to the app. Returns True on failure."""
        steam_id = self.app.resolve_local_account(account)
        if steam_id is None:
            # Steam has never signed this account in on this machine; the app
            # signs it in once so the ID lands in loginusers.vdf.
            self.app.call_on_ui(
                messagebox.showinfo,
                "First sign-in",
                f"Steam has not seen {account} yet. Signing in once so the "
                "account is registered; start it again afterwards.",
            )
            self.app.sign_in_once(account, password)
            return True

        order = Order(steam_id64=steam_id, amount=amount, slot=slot)
        problem = self._place(order, account=account, password=password,
                              shared_secret=shared_secret)
        if problem:
            self.app.call_on_ui(messagebox.showerror, "Cannot start", problem)
            return True

        self.app.call_on_ui(self.refresh)
        return False

    def _place(
        self,
        order: Order,
        *,
        account: str | None = None,
        password: str | None = None,
        shared_secret: str | None = None,
    ) -> str | None:
        """Run the rules, reserve the budget and create the job.

        Returns ``None`` on success or a message describing the refusal.
        """
        database = self.app.database
        if database is None or self.app.user is None:
            return "Not connected to the server."

        user_id = int(self.app.user["userid"])
        balance = database.get_balance(user_id, order.slot.id) or Balance(0, 0)

        decision = validate_order(
            order,
            balance,
            active_jobs=database.count_active_jobs(self.app.hwid),
            is_reseller=bool(self.app.user.get("reseller")),
            target_blacklisted=database.is_steam_id_blacklisted(order.steam_id64),
            target_already_running=database.get_job(order.steam_id64) is not None,
        )
        if not decision.accepted:
            return describe(decision)

        # Reserve first: if the budget went while the rules were being checked,
        # this returns None and nothing has been created yet.
        reserved = database.reserve_slot_currency(order.slot.id, order.amount)
        if reserved is None:
            return "The slot balance was used up a moment ago."

        try:
            database.create_job(
                steam_id64=order.steam_id64,
                user_id=user_id,
                hwid=self.app.hwid,
                amount=order.amount,
                slot=order.slot,
                previous_balance=balance.amount,
            )
        except Exception as exc:  # noqa: BLE001 - give the budget back on any failure
            database.refund_slot_currency(order.slot.id, order.amount)
            log.exception("creating the job failed")
            return f"Could not create the job: {exc}"

        if account and password:
            self.app.launch_runner(order.steam_id64, account, password, shared_secret)
        return None

    def _build_order(self, raw_amount: str, slot_label: str) -> Order | None:
        """Parse the amount and slot shared by both tabs; ``None`` if unusable."""
        amount = raw_amount.strip()
        if not amount.isdigit():
            return None
        slot = self._slot_from_label(slot_label)
        if slot is None:
            return None
        return Order(steam_id64=0, amount=int(amount), slot=slot)

    def _slot_from_label(self, label: str) -> Slot | None:
        """Find the slot behind a ``"3.Fast"`` drop-down entry."""
        try:
            slot_id = parse_slot_label(label)
        except ValueError:
            return None
        return next((slot for slot in self.slots if slot.id == slot_id), None)

    # --- the two action buttons ------------------------------------------

    def on_stop(self) -> None:
        """"Confirm" starts a queued job; "Stop" asks the backend to end it."""
        database = self.app.database
        if database is None or self.selected_account is None:
            return
        raw = database.server_users.find_one({"steamID64": self.selected_account})
        if raw is None:
            return

        kind = "start" if self.stop_button.cget("text") == "Confirm" else "stop"
        database.queue_command(raw, self.app.hwid, kind)
        self._set_buttons(stop="Stop", pause="Pause", enabled=False)

    def on_pause(self) -> None:
        """"Cancel" drops the job and refunds it; "Pause" is backend-driven."""
        database = self.app.database
        if database is None or self.selected_account is None:
            return
        if self.pause_button.cget("text") != "Cancel":
            return

        removed = database.delete_job(self.selected_account)
        if removed:
            database.refund_slot_currency(removed["slot_id"], removed["amount"])
        self.selected_account = None
        self.refresh()

    # --- activity log -----------------------------------------------------

    def add_log(self, text: str) -> None:
        """Append one line to the activity strip, oldest lines dropping off."""
        row = ctk.CTkLabel(
            self.log_list.inner, text=text, font=("Roboto", 11), justify="left"
        )
        row.pack(anchor="nw", pady=1)
        self._log_rows.append(row)

        while len(self._log_rows) > 40:
            self._log_rows.pop(0).destroy()
