"""Steam Guard two-factor codes.

A ``shared_secret`` is the seed Steam's mobile authenticator uses. Supplying one
lets the panel type the login code itself instead of waiting for a human.

Treat it as a credential of the same weight as the password: anyone holding it
can log into the account indefinitely. It is optional everywhere in this code
base, and accounts without one simply need someone at the keyboard.
"""

from __future__ import annotations

from base64 import b64decode
from binascii import Error as BinasciiError


class GuardError(RuntimeError):
    """Raised when a two-factor code cannot be produced."""


def generate_two_factor_code(shared_secret: str, timestamp: int | None = None) -> str:
    """Return the current 5-character Steam Guard code for ``shared_secret``.

    Args:
        shared_secret: the base64-encoded seed from the mobile authenticator.
        timestamp: Unix time to generate for; defaults to now.

    Raises:
        GuardError: if the secret is not valid base64 or the ``steam`` package
            is not installed.
    """
    try:
        from steam import guard  # noqa: PLC0415 - optional dependency
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise GuardError(
            "the 'steam' package is required to generate Steam Guard codes"
        ) from exc

    try:
        seed = b64decode(shared_secret, validate=True)
    except (BinasciiError, ValueError) as exc:
        raise GuardError("shared_secret is not valid base64") from exc

    if timestamp is None:
        return guard.generate_twofactor_code(seed)
    return guard.generate_twofactor_code_for_time(seed, timestamp)
