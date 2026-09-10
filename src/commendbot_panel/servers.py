"""The pool of CS:GO servers the runners are sent to.

The original build had the host names and the join password as a literal dict in
two different files, with the two copies already out of sync on the port numbers
(AUDIT.md S2). Here the pool is data: a JSON file named by
``COMMENDBOT_SERVERS_FILE``, shipped as ``servers.example.json``.

Server selection is pure — :func:`pick_best_server` takes the query function as
an argument — so it can be tested without touching the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GameServer:
    """One CS:GO server the panel is allowed to send accounts to."""

    name: str
    host: str
    port: int
    password: str = ""

    @property
    def address(self) -> tuple[str, int]:
        """Address tuple in the shape the A2S library expects."""
        return (self.host, self.port)

    def connect_url(self) -> str:
        """``steam://`` URL that makes a running client join this server."""
        suffix = f"/{self.password}" if self.password else ""
        return f"steam://connect/{self.host}:{self.port}{suffix}"

    def console_command(self) -> str:
        """The equivalent as a pair of console commands, for the copy button."""
        if not self.password:
            return f"connect {self.host}:{self.port}"
        return f"connect {self.host}:{self.port}; password {self.password}"


@dataclass(frozen=True)
class ServerLoad:
    """A single A2S sample: how full a server was when we asked."""

    players: int
    slots: int

    @property
    def occupancy(self) -> float:
        """Fraction of slots in use; a server reporting no slots counts as full."""
        if self.slots <= 0:
            return 1.0
        return self.players / self.slots


# A query function maps a server to its current load, or to None if it did not answer.
QueryFn = Callable[[GameServer], ServerLoad | None]


def load_servers(path: Path) -> tuple[GameServer, ...]:
    """Read the server pool from a JSON file.

    The file is a list of objects with ``name``, ``host``, ``port`` and an
    optional ``password``.

    Raises:
        ValueError: if the file is not a list of objects with the required keys.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of servers")

    servers = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict) or "host" not in entry or "port" not in entry:
            raise ValueError(f"{path}: entry {index} needs at least 'host' and 'port'")
        servers.append(
            GameServer(
                name=str(entry.get("name") or entry["host"]),
                host=str(entry["host"]),
                port=int(entry["port"]),
                password=str(entry.get("password", "")),
            )
        )
    return tuple(servers)


def pick_best_server(
    servers: Sequence[GameServer],
    query: QueryFn,
    *,
    rounds: int = 1,
) -> GameServer | None:
    """Return the least busy server that answered, or ``None`` if none did.

    Args:
        servers: the pool to choose from.
        query: how to sample one server; return ``None`` for no answer.
        rounds: how many times to sample the whole pool. The original code
            always scanned twice per attempt with no way to turn it off, which
            doubled start-up latency for no benefit.

    A server that is completely full is still a valid answer — it is better to
    return a full server than to return nothing and stall the runner.
    """
    best: tuple[GameServer, float] | None = None

    for _ in range(max(1, rounds)):
        for server in servers:
            load = query(server)
            if load is None:
                continue
            if best is None or load.occupancy < best[1]:
                best = (server, load.occupancy)

    return best[0] if best else None


def first_or_none(servers: Iterable[GameServer]) -> GameServer | None:
    """Fallback used when every server in the pool is unreachable."""
    return next(iter(servers), None)
