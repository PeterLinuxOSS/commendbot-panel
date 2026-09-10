"""The panel side of the control channel.

One listener on loopback, one thread per connected runner. Compared with the
original:

* a connection must present the shared token before it is registered, so a
  stray local process can no longer send ``close`` to every running game
  (AUDIT.md B3);
* the registry of connections is guarded by a lock and cleaned up in a
  ``finally``, instead of ``del clients[steamid]`` on a line that raised
  ``KeyError`` whenever a client dropped before identifying itself
  (AUDIT.md A17);
* :meth:`ControlServer.stop` actually stops the accept loop. The old flag was
  only examined after ``accept()`` returned, so the loop stayed blocked
  forever and the process had to be killed.
"""

from __future__ import annotations

import contextlib
import logging
import socket
import threading
from collections.abc import Callable

from ..constants import IPC_HOST, IPC_PORT, IPC_READ_SIZE
from . import protocol
from .protocol import Message, MessageReader, ProtocolError

log = logging.getLogger(__name__)

# How often the accept loop wakes up to notice that stop() was called.
_ACCEPT_TIMEOUT_SECONDS = 0.5

# A runner that does not identify itself this quickly is dropped.
_HANDSHAKE_TIMEOUT_SECONDS = 30.0


class AddressInUseError(RuntimeError):
    """Raised when the control port is already taken — usually a second panel."""


class RunnerConnection:
    """One connected runner, identified by the Steam account it is driving."""

    def __init__(self, sock: socket.socket, steam_id64: int) -> None:
        self.socket = sock
        self.steam_id64 = steam_id64
        self._send_lock = threading.Lock()

    def send(self, verb: str, *args: object) -> bool:
        """Send one message. Returns False if the connection has gone away."""
        with self._send_lock:
            try:
                self.socket.sendall(protocol.encode(verb, *args))
            except OSError:
                return False
        return True

    def close(self) -> None:
        """Close the socket, ignoring the state it happens to be in."""
        with contextlib.suppress(OSError):
            self.socket.close()


# Called for every message from a runner, on that runner's thread.
Handler = Callable[[RunnerConnection, Message], None]


class ControlServer:
    """Accepts runner connections and dispatches their messages."""

    def __init__(
        self,
        token: str,
        handler: Handler,
        *,
        host: str = IPC_HOST,
        port: int = IPC_PORT,
    ) -> None:
        self._token = token
        self._handler = handler
        self._host = host
        self._port = port
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._connections: dict[int, RunnerConnection] = {}

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Bind the port and begin accepting in a daemon thread.

        Raises:
            AddressInUseError: if another panel already holds the port.
        """
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self._host, self._port))
        except OSError as exc:
            listener.close()
            raise AddressInUseError(
                f"{self._host}:{self._port} is in use — another panel is running"
            ) from exc

        listener.listen()
        listener.settimeout(_ACCEPT_TIMEOUT_SECONDS)
        self._socket = listener
        self._thread = threading.Thread(
            target=self._accept_loop, name="ipc-accept", daemon=True
        )
        self._thread.start()
        log.info("control server listening on %s:%s", self._host, self._port)

    def stop(self, timeout: float = 2.0) -> None:
        """Stop accepting, drop every runner and wait for the thread to finish."""
        self._stopping.set()
        if self._socket is not None:
            with contextlib.suppress(OSError):
                self._socket.close()
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
        for connection in connections:
            connection.close()
        if self._thread is not None:
            self._thread.join(timeout)

    # --- talking to runners ----------------------------------------------

    @property
    def steam_ids(self) -> list[int]:
        """Steam accounts that currently have a live runner."""
        with self._lock:
            return sorted(self._connections)

    def send_to(self, steam_id64: int, verb: str, *args: object) -> bool:
        """Send to one runner. Returns False when that runner is not connected."""
        with self._lock:
            connection = self._connections.get(steam_id64)
        return connection.send(verb, *args) if connection else False

    def broadcast(self, verb: str, *args: object) -> None:
        """Send to every connected runner, ignoring the ones that have died."""
        with self._lock:
            connections = list(self._connections.values())
        for connection in connections:
            connection.send(verb, *args)

    # --- internals --------------------------------------------------------

    def _accept_loop(self) -> None:
        listener = self._socket
        if listener is None:  # pragma: no cover - start() always sets it
            return
        while not self._stopping.is_set():
            try:
                conn, _address = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                # The listener was closed by stop(); that is the exit signal.
                break
            threading.Thread(
                target=self._serve, args=(conn,), name="ipc-runner", daemon=True
            ).start()

    def _serve(self, conn: socket.socket) -> None:
        """Handshake, then pump messages until the runner disconnects."""
        connection: RunnerConnection | None = None
        reader = MessageReader()
        conn.settimeout(_HANDSHAKE_TIMEOUT_SECONDS)

        try:
            while not self._stopping.is_set():
                try:
                    chunk = conn.recv(IPC_READ_SIZE)
                except (TimeoutError, OSError):
                    break
                if not chunk:
                    break

                try:
                    messages = reader.feed(chunk)
                except ProtocolError:
                    log.warning("dropping a peer that is not speaking the protocol")
                    break

                for message in messages:
                    if connection is None:
                        connection = self._authenticate(conn, message)
                        if connection is None:
                            return
                        # Identified: no more handshake deadline. The HELLO is
                        # still handed to the application — that is where the
                        # panel answers with settings and credentials.
                        conn.settimeout(None)
                        self._dispatch(connection, message)
                        continue
                    self._dispatch(connection, message)
        finally:
            if connection is not None:
                self._forget(connection)
            with contextlib.suppress(OSError):
                conn.close()

    def _authenticate(
        self, conn: socket.socket, message: Message
    ) -> RunnerConnection | None:
        """Validate ``HELLO <token> <steam_id64>`` and register the runner."""
        if message.verb != protocol.HELLO or len(message.args) < 2:
            _try_send(conn, protocol.DENIED, "handshake expected")
            return None

        token, raw_id = message.args[0], message.args[1]
        if token != self._token:
            log.warning("rejected a connection with a bad token")
            _try_send(conn, protocol.DENIED, "bad token")
            return None
        if not raw_id.isdigit():
            _try_send(conn, protocol.DENIED, "bad steam id")
            return None

        connection = RunnerConnection(conn, int(raw_id))
        with self._lock:
            previous = self._connections.get(connection.steam_id64)
            self._connections[connection.steam_id64] = connection
        if previous is not None:
            # A restarted runner replaces the stale connection for that account.
            previous.close()

        connection.send(protocol.READY)
        log.info("runner connected for %s", connection.steam_id64)
        return connection

    def _dispatch(self, connection: RunnerConnection, message: Message) -> None:
        """Hand a message to the application, never letting it kill the thread."""
        try:
            self._handler(connection, message)
        except Exception:
            log.exception("handler failed for %s", message.verb)

    def _forget(self, connection: RunnerConnection) -> None:
        """Remove a runner from the registry if it is still the current one."""
        with self._lock:
            if self._connections.get(connection.steam_id64) is connection:
                del self._connections[connection.steam_id64]
        log.info("runner for %s disconnected", connection.steam_id64)


def _try_send(conn: socket.socket, verb: str, *args: object) -> None:
    """Send a final message to a peer we are about to drop; failure is fine."""
    with contextlib.suppress(OSError):
        conn.sendall(protocol.encode(verb, *args))
