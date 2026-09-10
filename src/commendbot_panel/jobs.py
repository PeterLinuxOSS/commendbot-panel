"""Deciding whether a commend order may be placed.

This module is deliberately free of Tk, MongoDB and Steam. The original code
made the same decision twice — once in ``link_commend`` and once in
``local_commend`` — as two ~90-line ladders of nested ``if``/``else`` that had
drifted apart. Both copies carried the same two defects:

* the "minimum commends" message named ``min_commends`` while the check
  compared against ``0`` (AUDIT.md A5);
* ``tdb >= 5 or tdb >= 5 and userid != …`` collapses to ``tdb >= 5`` because
  ``and`` binds tighter than ``or``, so the exempt account was never exempt
  (AUDIT.md A6).

Having one pure function means both entry points agree and the rules are
testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .constants import MAX_CONCURRENT_JOBS, RESELLER_ONLY_JOBS

# A slot value of 0 means "no limit" in the shared database schema.
_UNLIMITED = 0


class Rejection(Enum):
    """Why an order was refused. The UI turns these into user-facing text."""

    SLOT_DISABLED = "slot_disabled"
    BELOW_MINIMUM = "below_minimum"
    ABOVE_MAXIMUM = "above_maximum"
    SLOT_EXHAUSTED = "slot_exhausted"
    DAILY_LIMIT = "daily_limit"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    TARGET_BLACKLISTED = "target_blacklisted"
    ALREADY_RUNNING = "already_running"
    TOO_MANY_JOBS = "too_many_jobs"
    RESELLER_ONLY = "reseller_only"


@dataclass(frozen=True)
class Slot:
    """A commend slot as configured in the shared database."""

    id: int
    name: str
    enabled: bool
    currency: int
    min_commends: int = 0
    max_commends: int = _UNLIMITED
    max_daily_commends: int = _UNLIMITED
    commend_channel_id: int | None = None

    @property
    def label(self) -> str:
        """How the slot is shown in the drop-downs: ``3.Fast``."""
        return f"{self.id}.{self.name}"


@dataclass(frozen=True)
class Balance:
    """One user's remaining and already-used commends for a single slot."""

    amount: int
    today_used: int = 0


@dataclass(frozen=True)
class Order:
    """A request to commend one account a given number of times."""

    steam_id64: int
    amount: int
    slot: Slot


@dataclass(frozen=True)
class Decision:
    """Outcome of :func:`validate_order`."""

    rejection: Rejection | None = None
    detail: str = ""

    @property
    def accepted(self) -> bool:
        """True when the order may proceed."""
        return self.rejection is None


ACCEPTED = Decision()


def validate_order(
    order: Order,
    balance: Balance,
    *,
    active_jobs: int,
    is_reseller: bool = False,
    target_blacklisted: bool = False,
    target_already_running: bool = False,
) -> Decision:
    """Apply every rule that governs placing a commend order.

    Args:
        order: what the operator asked for.
        balance: the operator's remaining commends on that slot.
        active_jobs: how many jobs this machine is already running.
        is_reseller: resellers may exceed the soft concurrency limit.
        target_blacklisted: the target Steam account is banned from the service.
        target_already_running: a job for that account already exists.

    Returns:
        :data:`ACCEPTED`, or a :class:`Decision` naming the first rule that failed.
        Rules are checked cheapest-first so the message points at the real cause.
    """
    slot = order.slot

    if not slot.enabled:
        return Decision(Rejection.SLOT_DISABLED)

    if order.amount < max(slot.min_commends, 1):
        return Decision(
            Rejection.BELOW_MINIMUM, f"minimum is {max(slot.min_commends, 1)}"
        )

    maximum = slot.max_commends
    if maximum != _UNLIMITED and order.amount > maximum:
        return Decision(Rejection.ABOVE_MAXIMUM, f"maximum is {maximum}")

    if order.amount > slot.currency:
        return Decision(Rejection.SLOT_EXHAUSTED)

    daily_cap = slot.max_daily_commends
    if daily_cap != _UNLIMITED and balance.today_used + order.amount > daily_cap:
        remaining = max(daily_cap - balance.today_used, 0)
        return Decision(Rejection.DAILY_LIMIT, f"{remaining} of {daily_cap} left today")

    if order.amount > balance.amount:
        return Decision(Rejection.INSUFFICIENT_BALANCE, f"{balance.amount} commends left")

    if target_blacklisted:
        return Decision(Rejection.TARGET_BLACKLISTED)

    if target_already_running:
        return Decision(Rejection.ALREADY_RUNNING)

    if active_jobs >= MAX_CONCURRENT_JOBS:
        return Decision(
            Rejection.TOO_MANY_JOBS, f"{active_jobs} of {MAX_CONCURRENT_JOBS} in use"
        )

    if active_jobs >= RESELLER_ONLY_JOBS and not is_reseller:
        return Decision(
            Rejection.RESELLER_ONLY, f"more than {RESELLER_ONLY_JOBS} at once"
        )

    return ACCEPTED


MESSAGES = {
    Rejection.SLOT_DISABLED: "This slot is disabled.",
    Rejection.BELOW_MINIMUM: "That is fewer commends than the slot allows.",
    Rejection.ABOVE_MAXIMUM: "That is more commends than the slot allows.",
    Rejection.SLOT_EXHAUSTED: "The slot balance is used up until 00:00 UTC.",
    Rejection.DAILY_LIMIT: "Your daily balance for this slot is used up.",
    Rejection.INSUFFICIENT_BALANCE: "Not enough commends on your balance.",
    Rejection.TARGET_BLACKLISTED: "This Steam account is blacklisted.",
    Rejection.ALREADY_RUNNING: "This account is already being commended.",
    Rejection.TOO_MANY_JOBS: "You reached the multi-commending limit.",
    Rejection.RESELLER_ONLY: "Only resellers may run that many accounts at once.",
}


def describe(decision: Decision) -> str:
    """Render a decision as one line of user-facing text."""
    if decision.accepted:
        return ""
    text = MESSAGES.get(decision.rejection, "The order was refused.")
    return f"{text} ({decision.detail})" if decision.detail else text


def parse_slot_label(label: str) -> int:
    """Extract the slot id from a ``"3.Fast"`` drop-down label.

    Raises:
        ValueError: if the label does not start with a number.
    """
    head = label.split(".", 1)[0].strip()
    if not head.isdigit():
        raise ValueError(f"{label!r} does not start with a slot id")
    return int(head)


@dataclass(frozen=True)
class BulkEntry:
    """One line of a mass-commend import file."""

    login: str
    password: str
    amount: int
    shared_secret: str | None = None


def parse_bulk_line(line: str) -> BulkEntry:
    """Parse ``login:password:amount[:shared_secret]``.

    Raises:
        ValueError: if the field count is wrong or the amount is not a number.
    """
    parts = line.strip().split(":")
    if len(parts) not in (3, 4):
        raise ValueError("expected login:password:amount[:shared_secret]")

    login, password, amount = parts[0], parts[1], parts[2]
    if not amount.strip().lstrip("+").isdigit():
        raise ValueError(f"{amount!r} is not a number")
    if not login.strip() or not password:
        raise ValueError("login and password must not be empty")

    secret = parts[3].strip() if len(parts) == 4 and parts[3].strip() else None
    return BulkEntry(login.strip(), password, int(amount), secret)


def parse_bulk_file(text: str) -> list[BulkEntry]:
    """Parse a whole import file, skipping blank lines and ``#`` comments.

    Raises:
        ValueError: naming the first offending line number.
    """
    entries: list[BulkEntry] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entries.append(parse_bulk_line(line))
        except ValueError as exc:
            raise ValueError(f"line {number}: {exc}") from exc
    return entries
