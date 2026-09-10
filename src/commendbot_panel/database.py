"""MongoDB access.

The panel shares its database with a Discord bot that is not part of this
repository, so the collection names and document shapes here are a contract with
that other program and are reproduced faithfully.

What changed from the original:

* the connection string comes from the environment, never from the source;
* the ``db`` namespace was a class declared *inside* a function inside a
  ``try/else``, so a failed connection left the name undefined and every later
  reference raised ``NameError``. It is a real object now, and failure to
  connect raises :class:`DatabaseError` at the call site;
* spending slot currency is a single conditional update instead of
  read-then-write, closing the double-spend window the original author had
  already flagged with a comment (AUDIT.md B6);
* every timestamp is taken when the record is written. The original captured
  the current time once at import and stamped every document with the moment
  the panel was launched (AUDIT.md A10).
"""

from __future__ import annotations

import contextlib
import datetime as dt
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .constants import STATUS_WAITING_CONNECT
from .jobs import Balance, Slot


class DatabaseError(RuntimeError):
    """Raised when the database is unreachable or rejects an operation."""


def utc_now() -> dt.datetime:
    """Current UTC time. One place to patch in tests."""
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class JobRecord:
    """A row of ``serverusers``: one account currently being commended."""

    steam_id64: int
    status: str
    amount: int
    received: int
    pending: int
    chunk: str
    chunk_info: str
    slot_id: int
    ends_at: float | None = None
    reason: str = ""

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> JobRecord:
        """Build a record from a raw Mongo document, tolerating missing keys.

        Documents are written by two programs; treating an absent field as a
        zero is what keeps the panel from crashing on a partially-written row.
        """
        return cls(
            steam_id64=int(doc.get("steamID64", 0)),
            status=str(doc.get("status", STATUS_WAITING_CONNECT)),
            amount=int(doc.get("amount", 0)),
            received=int(doc.get("actualamount", 0)),
            pending=int(doc.get("lastpending", 0)),
            chunk=str(doc.get("chunk", "#0")),
            chunk_info=str(doc.get("chunk-info", "[0/0]")),
            slot_id=int(doc.get("slot_id", 0)),
            ends_at=doc.get("endeta"),
            reason=str(doc.get("reason", "")),
        )


class Database:
    """Typed access to the collections the panel uses."""

    def __init__(self, client: Any) -> None:
        self._client = client
        servers = client["servers"]
        users = client["usersdb"]

        # Names kept as they are in the shared deployment.
        self.users = users["usersdb"]
        self.balances = users["balancesdb"]
        self.slots = servers["commendbotstatus"]
        self.server_users = servers["serverusers"]
        self.waiting_list = servers["waitinglist"]
        self.blacklist = servers["blacklistdb"]
        self.errors = servers["errors"]
        self._servers_db = servers

    @classmethod
    def connect(cls, uri: str, *, timeout_ms: int = 3000) -> Database:
        """Open a connection.

        Raises:
            DatabaseError: if pymongo is missing or the URI cannot be used.
        """
        try:
            from pymongo import MongoClient  # noqa: PLC0415 - optional at import time
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise DatabaseError("pymongo is not installed") from exc

        try:
            client = MongoClient(uri, connectTimeoutMS=timeout_ms)
        except Exception as exc:  # pragma: no cover - driver-specific
            raise DatabaseError(f"cannot connect: {exc}") from exc
        return cls(client)

    def close(self) -> None:
        """Release the driver's sockets."""
        self._client.close()

    # --- authentication ---------------------------------------------------

    def find_user(self, login: str, password: str) -> dict[str, Any] | None:
        """Look up a panel account. Returns ``None`` when the pair is unknown."""
        return self.users.find_one({"login": login.strip(), "password": password.strip()})

    def bind_machine(self, user_id: Any, hwid: str) -> None:
        """Record which machine an account is tied to, on first login."""
        self.users.update_one({"_id": user_id}, {"$set": {"hwid": hwid}})

    def is_user_blacklisted(self, user_id: int) -> bool:
        """True when the panel account itself is banned."""
        return self.blacklist.find_one({"userid": user_id}) is not None

    def is_steam_id_blacklisted(self, steam_id64: int) -> bool:
        """True when the *target* Steam account may not be commended."""
        return self.blacklist.find_one({"steamID64": steam_id64}) is not None

    # --- slots and balances ----------------------------------------------

    def list_slots(self) -> list[Slot]:
        """Every configured slot, ordered by id."""
        return [_slot_from_document(doc) for doc in self.slots.find({}).sort("_id", 1)]

    def get_slot(self, slot_id: int) -> Slot | None:
        """One slot, or ``None`` if it has been removed."""
        doc = self.slots.find_one({"_id": slot_id})
        return _slot_from_document(doc) if doc else None

    def get_balance(self, user_id: int, slot_id: int) -> Balance | None:
        """A user's balance on one slot, or ``None`` if they have none."""
        doc = self.balances.find_one({"userid": user_id, "slot_id": slot_id})
        if not doc:
            return None
        return Balance(
            amount=int(doc.get("amount", 0)), today_used=int(doc.get("today_used", 0))
        )

    def reserve_slot_currency(self, slot_id: int, amount: int) -> Slot | None:
        """Atomically take ``amount`` off a slot's daily budget.

        Returns the updated slot, or ``None`` when the budget was already too
        low — the guard is inside the query, so two panels racing cannot both
        succeed.
        """
        from pymongo import ReturnDocument  # noqa: PLC0415

        doc = self.slots.find_one_and_update(
            {"_id": slot_id, "currency": {"$gte": amount}},
            {"$inc": {"currency": -amount}},
            return_document=ReturnDocument.AFTER,
        )
        return _slot_from_document(doc) if doc else None

    def refund_slot_currency(self, slot_id: int, amount: int) -> None:
        """Give a reservation back after a cancelled job."""
        self.slots.update_one({"_id": slot_id}, {"$inc": {"currency": amount}})

    # --- jobs -------------------------------------------------------------

    def count_active_jobs(self, hwid: str) -> int:
        """How many accounts this machine is commending right now."""
        return self.server_users.count_documents({"hwid": hwid})

    def list_active_jobs(self, hwid: str) -> list[JobRecord]:
        """Every job this machine owns, oldest first."""
        cursor = self.server_users.find({"hwid": hwid}).sort("_id", 1)
        return [JobRecord.from_document(doc) for doc in cursor]

    def get_job(self, steam_id64: int) -> JobRecord | None:
        """The job for one Steam account, if there is one."""
        doc = self.server_users.find_one({"steamID64": steam_id64})
        return JobRecord.from_document(doc) if doc else None

    def create_job(
        self,
        *,
        steam_id64: int,
        user_id: int,
        hwid: str,
        amount: int,
        slot: Slot,
        previous_balance: int,
    ) -> dict[str, Any]:
        """Insert a new job and return the stored document."""
        document = {
            "_id": steam_id64,
            "steamID64": steam_id64,
            "userid": user_id,
            "hwid": hwid,
            "amount": amount,
            "actualamount": 0,
            "lastpending": 0,
            "pendingmany": 0,
            "commended": False,
            "auto": False,
            "status": STATUS_WAITING_CONNECT,
            "slot_id": slot.id,
            "chunk": "#0",
            "chunk-info": "[0/0]",
            "commend_channelid": slot.commend_channel_id,
            "old_balance": previous_balance,
            "lastup": utc_now(),
        }
        self.server_users.insert_one(document)
        return document

    def delete_job(self, steam_id64: int) -> dict[str, Any] | None:
        """Remove a job and return the document as it was."""
        return self.server_users.find_one_and_delete({"steamID64": steam_id64})

    def queue_command(self, job: dict[str, Any], hwid: str, kind: str) -> None:
        """Ask the backend to start or stop a job.

        The panel never flips a job's status itself; it appends to
        ``waitinglist`` and the bot acts on it.
        """
        self.waiting_list.insert_one(
            {
                "slot_id": job["slot_id"],
                "steamID64": job["steamID64"],
                "amount": job["amount"],
                "status": "wait",
                "waitchannelid": job.get("commend_channelid"),
                "hwid": hwid,
                "type": kind,
                "datetime": utc_now(),
            }
        )

    def pending_command(self, steam_id64: int) -> dict[str, Any] | None:
        """The queued start/stop for an account, if the bot has not consumed it."""
        return self.waiting_list.find_one({"steamID64": steam_id64})

    # --- misc -------------------------------------------------------------

    def watch_jobs(self) -> Iterator[dict[str, Any]]:
        """Yield change-stream events for the shared ``servers`` database."""
        yield from self._servers_db.watch()

    def log_error(self, hwid: str, message: str, version: str) -> None:
        """Best-effort crash report. Never raises: it runs from error handlers."""
        with contextlib.suppress(Exception):
            self.errors.insert_one(
                {
                    "hwid": hwid,
                    "msg": message,
                    "version": version,
                    "datetime": utc_now(),
                }
            )


def _slot_from_document(doc: dict[str, Any]) -> Slot:
    """Translate a ``commendbotstatus`` document into a :class:`Slot`."""
    return Slot(
        id=int(doc["_id"]),
        name=str(doc.get("name", "")),
        enabled=bool(doc.get("enable", False)),
        currency=int(doc.get("currency", 0)),
        min_commends=int(doc.get("min_commends", 0)),
        max_commends=int(doc.get("max_commends", 0)),
        max_daily_commends=int(doc.get("max_daily_commends", 0)),
        commend_channel_id=doc.get("commend_channelid"),
    )
