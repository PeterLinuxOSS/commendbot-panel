"""Wire format for the loopback channel between the panel and its runners.

Three problems with the original protocol are fixed here.

*No framing.* Messages were raw ``recv(1024)`` buffers compared with ``==``.
Two messages sent close together arrived as one blob and matched nothing.
Messages are now newline-delimited and read through :class:`MessageReader`.

*No authentication.* Anything on the machine could connect to port 11569 and
send ``close``. A connection now has to open with the token the panel generated
at start-up and handed to the runner it spawned.

*Lossy booleans.* ``bool("0")`` is ``True``, which is why "Auto-Reconnect off"
never switched anything off. Flags travel as ``key=value`` and are parsed by
:func:`parse_bool`.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from ..constants import IPC_ENCODING, IPC_TERMINATOR

# --- Verbs the panel sends to a runner ------------------------------------

READY = "READY"          # handshake accepted
DENIED = "DENIED"        # bad token; the runner must exit
CONNECT = "CONNECT"      # CONNECT <steam://connect/...>
LAUNCH = "LAUNCH"        # bring CS:GO up via steam://rungameid
CLOSE = "CLOSE"          # shut the game and the runner down
RESTART = "RESTART"      # forget "already commending" state
SETTINGS = "SETTINGS"    # SETTINGS autoreconnect=1
CREDENTIALS = "CREDENTIALS"  # CREDENTIALS <account> <password>
FIND_LOGIN = "FIND_LOGIN"    # locate the Steam Guard window
TYPE_CODE = "TYPE_CODE"      # TYPE_CODE <5-char guard code>

# --- Verbs a runner sends to the panel ------------------------------------

HELLO = "HELLO"                # HELLO <token> <steam_id64>
STARTED = "STARTED"            # the account is on a server and commending
LOGIN_WINDOW = "LOGIN_WINDOW"  # LOGIN_WINDOW <hwnd>
BYE = "BYE"                    # clean shutdown


class ProtocolError(ValueError):
    """Raised when a line cannot be understood as a message."""


@dataclass(frozen=True)
class Message:
    """One protocol line: a verb plus zero or more positional arguments."""

    verb: str
    args: tuple[str, ...] = field(default_factory=tuple)

    def encode(self) -> bytes:
        """Serialise to a single newline-terminated line."""
        parts = [self.verb, *(shlex.quote(arg) for arg in self.args)]
        return (" ".join(parts) + IPC_TERMINATOR).encode(IPC_ENCODING)

    def arg(self, index: int, default: str = "") -> str:
        """Positional argument or ``default`` when it was not sent."""
        return self.args[index] if index < len(self.args) else default

    def flags(self) -> dict[str, str]:
        """Interpret the arguments as ``key=value`` pairs; others are ignored."""
        return dict(arg.split("=", 1) for arg in self.args if "=" in arg)


def encode(verb: str, *args: object) -> bytes:
    """Shorthand for ``Message(verb, args).encode()``."""
    return Message(verb, tuple(str(a) for a in args)).encode()


def decode(line: str) -> Message:
    """Parse one line into a :class:`Message`.

    Raises:
        ProtocolError: on an empty line or unbalanced quoting.
    """
    try:
        tokens = shlex.split(line.strip())
    except ValueError as exc:
        raise ProtocolError(f"malformed line: {line!r}") from exc
    if not tokens:
        raise ProtocolError("empty line")
    return Message(tokens[0].upper(), tuple(tokens[1:]))


def parse_bool(value: str) -> bool:
    """Interpret a wire value as a boolean.

    ``"0"``, ``"false"``, ``"no"``, ``"off"`` and the empty string are false;
    everything else is true. ``bool("0")`` — the original implementation — is
    ``True``, which silently disabled the Auto-Reconnect switch.
    """
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


class MessageReader:
    """Turns a byte stream into whole messages.

    Feed it whatever ``recv`` returned; it buffers partial lines and yields only
    complete ones.
    """

    def __init__(self, *, max_line: int = 64 * 1024) -> None:
        self._buffer = ""
        self._max_line = max_line

    def feed(self, chunk: bytes) -> list[Message]:
        """Add received bytes and return every complete message in them.

        Raises:
            ProtocolError: if a single line grows past ``max_line``, which means
                the peer is not speaking this protocol.
        """
        self._buffer += chunk.decode(IPC_ENCODING, errors="replace")
        if len(self._buffer) > self._max_line:
            raise ProtocolError("line too long")

        messages: list[Message] = []
        while IPC_TERMINATOR in self._buffer:
            line, self._buffer = self._buffer.split(IPC_TERMINATOR, 1)
            if line.strip():
                messages.append(decode(line))
        return messages
