"""The runner side of the control channel.

The reconnect budget here is the one thing worth reading twice. The original
decremented a countdown while retrying, but reset it to 60 in a ``finally`` that
ran on *every* pass of the outer loop, so it could never reach zero and a runner
whose panel had exited retried forever (AUDIT.md A3). The budget is now spent by
:meth:`ControlClient.connect`, and only a successful connection refills it.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Iterator

from ..constants import (
    IPC_HOST,
    IPC_PORT,
    IPC_READ_SIZE,
    RECONNECT_BUDGET_SECONDS,
    RECONNECT_STEP_SECONDS,
)
from . import protocol
from .protocol import Message, MessageReader, ProtocolError

log = logging.getLogger(__name__)


class HandshakeRejected(RuntimeError):
    """Raised when the panel refuses the token or the Steam ID."""


class ControlClient:
    """A runner's connection to the panel."""

    def __init__(
        self,
        token: str,
        steam_id64: int,
        *,
        host: str = IPC_HOST,
        port: int = IPC_PORT,
    ) -> None:
        self._token = token
        self._steam_id64 = steam_id64
        self._address = (host, port)
        self._socket: socket.socket | None = None
        self._reader = MessageReader()

    # --- connecting -------------------------------------------------------

    def connect(self, budget_seconds: int = RECONNECT_BUDGET_SECONDS) -> None:
        """Connect and complete the handshake, retrying until the budget runs out.

        Raises:
            ConnectionError: if the budget is exhausted without a connection.
            HandshakeRejected: if the panel answers ``DENIED``.
        """
        remaining = budget_seconds
        last_error: OSError | None = None

        while True:
            try:
                self._open()
            except OSError as exc:
                last_error = exc
                if remaining <= 0:
                    break
                log.info("panel not reachable, %ss of budget left", remaining)
                remaining -= RECONNECT_STEP_SECONDS
                time.sleep(RECONNECT_STEP_SECONDS)
                continue
            return

        raise ConnectionError(
            f"could not reach the panel at {self._address[0]}:{self._address[1]}"
        ) from last_error

    def _open(self) -> None:
        """One connection attempt, including the handshake."""
        sock = socket.create_connection(self._address, timeout=10)
        self._socket = sock
        self._reader = MessageReader()

        sock.sendall(protocol.encode(protocol.HELLO, self._token, self._steam_id64))
        reply = self._read_one(timeout=15)

        if reply is None or reply.verb == protocol.DENIED:
            detail = reply.arg(0, "no answer") if reply else "no answer"
            self.close()
            raise HandshakeRejected(f"the panel refused the connection: {detail}")

        if reply.verb != protocol.READY:
            self.close()
            raise HandshakeRejected(f"unexpected reply to the handshake: {reply.verb}")

        sock.settimeout(None)
        log.info("connected to the panel")

    def close(self) -> None:
        """Drop the connection; safe to call more than once."""
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    # --- messaging --------------------------------------------------------

    def send(self, verb: str, *args: object) -> bool:
        """Send one message. Returns False when the panel has gone away."""
        if self._socket is None:
            return False
        try:
            self._socket.sendall(protocol.encode(verb, *args))
        except OSError:
            return False
        return True

    def messages(self) -> Iterator[Message]:
        """Yield messages until the panel disconnects.

        The iterator ends on disconnect rather than raising, so the caller can
        decide whether to reconnect or shut down.
        """
        while self._socket is not None:
            try:
                chunk = self._socket.recv(IPC_READ_SIZE)
            except OSError:
                break
            if not chunk:
                break
            try:
                yield from self._reader.feed(chunk)
            except ProtocolError:
                log.warning("ignoring an unparseable line from the panel")
                break
        self.close()

    def _read_one(self, timeout: float) -> Message | None:
        """Block for a single message, used only during the handshake."""
        if self._socket is None:
            return None
        self._socket.settimeout(timeout)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                chunk = self._socket.recv(IPC_READ_SIZE)
            except (TimeoutError, OSError):
                return None
            if not chunk:
                return None
            try:
                messages = self._reader.feed(chunk)
            except ProtocolError:
                return None
            if messages:
                return messages[0]
        return None
