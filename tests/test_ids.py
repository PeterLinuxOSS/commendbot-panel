import pytest

from commendbot_panel.constants import STEAM_ID64_BASE
from commendbot_panel.steam.ids import (
    looks_like_steam_id64,
    parse_steam_id,
    to_steam_id32,
    to_steam_id64,
)

ID64 = 76561198012345678
ID32 = ID64 - STEAM_ID64_BASE


def test_to_steam_id32_subtracts_the_base_offset():
    assert to_steam_id32(ID64) == ID32


def test_to_steam_id32_rejects_a_value_below_the_base():
    with pytest.raises(ValueError):
        to_steam_id32(STEAM_ID64_BASE - 1)


def test_to_steam_id64_is_the_inverse_of_to_steam_id32():
    assert to_steam_id64(to_steam_id32(ID64)) == ID64


def test_to_steam_id64_rejects_a_negative_account_id():
    with pytest.raises(ValueError):
        to_steam_id64(-1)


def test_looks_like_steam_id64_accepts_seventeen_digits_with_whitespace():
    assert looks_like_steam_id64(f"  {ID64}  ") is True


def test_looks_like_steam_id64_rejects_a_short_number():
    assert looks_like_steam_id64("7656119801") is False


def test_parse_steam_id_accepts_a_bare_id64():
    assert parse_steam_id(str(ID64)) == ID64


def test_parse_steam_id_accepts_a_profiles_url():
    assert parse_steam_id(f"https://steamcommunity.com/profiles/{ID64}/") == ID64


def test_parse_steam_id_rejects_a_profiles_url_with_a_malformed_id():
    assert parse_steam_id("https://steamcommunity.com/profiles/12345") is None


def test_parse_steam_id_returns_none_for_a_vanity_url_without_a_resolver():
    assert parse_steam_id("https://steamcommunity.com/id/gaben") is None


def test_parse_steam_id_uses_the_injected_resolver_for_a_vanity_url():
    seen = []

    def resolve(name):
        seen.append(name)
        return ID64

    assert (
        parse_steam_id("https://steamcommunity.com/id/gaben", resolve_vanity=resolve)
        == ID64
    )
    assert seen == ["gaben"]


def test_parse_steam_id_returns_none_when_the_resolver_finds_nothing():
    assert (
        parse_steam_id("steamcommunity.com/id/nobody", resolve_vanity=lambda name: None)
        is None
    )


def test_parse_steam_id_returns_none_for_junk():
    assert parse_steam_id("not a steam id at all") is None


def test_parse_steam_id_returns_none_for_empty_input():
    assert parse_steam_id("") is None
    assert parse_steam_id(None) is None
