import json

import pytest

from commendbot_panel.servers import (
    GameServer,
    ServerLoad,
    first_or_none,
    load_servers,
    pick_best_server,
)

BUSY = GameServer("Busy", "10.0.0.1", 27015, "secret")
QUIET = GameServer("Quiet", "10.0.0.2", 27016)
BROKEN = GameServer("Broken", "10.0.0.3", 27017)


def test_address_is_a_host_port_tuple():
    assert BUSY.address == ("10.0.0.1", 27015)


def test_connect_url_appends_the_password():
    assert BUSY.connect_url() == "steam://connect/10.0.0.1:27015/secret"


def test_connect_url_omits_the_password_when_there_is_none():
    assert QUIET.connect_url() == "steam://connect/10.0.0.2:27016"


def test_console_command_adds_a_password_command_only_when_needed():
    assert BUSY.console_command() == "connect 10.0.0.1:27015; password secret"
    assert QUIET.console_command() == "connect 10.0.0.2:27016"


def test_server_load_occupancy_is_the_filled_fraction():
    assert ServerLoad(players=5, slots=20).occupancy == 0.25


def test_server_load_with_zero_slots_counts_as_full():
    assert ServerLoad(players=0, slots=0).occupancy == 1.0


def test_pick_best_server_returns_none_when_nothing_answers():
    assert pick_best_server([BUSY, QUIET, BROKEN], lambda server: None) is None


def test_pick_best_server_returns_none_for_an_empty_pool():
    assert pick_best_server([], lambda server: ServerLoad(0, 10)) is None


def test_pick_best_server_picks_the_lowest_occupancy():
    loads = {
        BUSY: ServerLoad(18, 20),
        QUIET: ServerLoad(2, 20),
        BROKEN: ServerLoad(10, 20),
    }
    assert pick_best_server([BUSY, QUIET, BROKEN], loads.get) is QUIET


def test_pick_best_server_skips_the_servers_that_did_not_answer():
    loads = {QUIET: ServerLoad(19, 20)}
    assert pick_best_server([BUSY, QUIET, BROKEN], loads.get) is QUIET


def test_pick_best_server_treats_a_zero_slot_server_as_full():
    loads = {BUSY: ServerLoad(0, 0), QUIET: ServerLoad(20, 20)}
    # both are at occupancy 1.0, so the first one sampled wins and neither is preferred over a real answer
    assert pick_best_server([BUSY, QUIET], loads.get) is BUSY
    assert (
        pick_best_server(
            [BUSY, QUIET], {BUSY: ServerLoad(0, 0), QUIET: ServerLoad(19, 20)}.get
        )
        is QUIET
    )


def test_pick_best_server_returns_a_full_server_rather_than_nothing():
    assert pick_best_server([BUSY], lambda server: ServerLoad(20, 20)) is BUSY


def test_pick_best_server_samples_the_pool_once_per_round():
    calls = []

    def query(server):
        calls.append(server)
        return ServerLoad(1, 10)

    pick_best_server([BUSY, QUIET], query, rounds=2)
    assert calls == [BUSY, QUIET, BUSY, QUIET]


def test_pick_best_server_still_samples_once_when_rounds_is_zero():
    calls = []
    pick_best_server([BUSY], lambda s: calls.append(s) or ServerLoad(1, 10), rounds=0)
    assert len(calls) == 1


def test_first_or_none_returns_none_for_an_empty_pool():
    assert first_or_none([]) is None
    assert first_or_none([QUIET, BUSY]) is QUIET


def test_load_servers_reads_the_pool_from_json(tmp_path):
    path = tmp_path / "servers.json"
    path.write_text(
        json.dumps(
            [
                {"name": "One", "host": "a.example", "port": "27015", "password": "pw"},
                {"host": "b.example", "port": 27016},
            ]
        ),
        encoding="utf-8",
    )
    servers = load_servers(path)
    assert servers == (
        GameServer("One", "a.example", 27015, "pw"),
        GameServer("b.example", "b.example", 27016, ""),
    )


def test_load_servers_rejects_a_file_that_is_not_a_list(tmp_path):
    path = tmp_path / "servers.json"
    path.write_text('{"host": "a.example"}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_servers(path)


def test_load_servers_rejects_an_entry_without_a_port(tmp_path):
    path = tmp_path / "servers.json"
    path.write_text('[{"host": "a.example"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="entry 0"):
        load_servers(path)
