from pathlib import Path

from commendbot_panel.steam.loginusers import (
    _minimal_vdf,
    find_steam_id_by_account,
    login_users_path,
    parse_login_users,
)

# Shape of a real config/loginusers.vdf, three accounts, tabs and all.
LOGINUSERS_VDF = """"users"
{
\t"76561198012345678"
\t{
\t\t"AccountName"\t\t"CommendBot_One"
\t\t"PersonaName"\t\t"one"
\t\t"RememberPassword"\t\t"1"
\t\t"MostRecent"\t\t"1"
\t\t"Timestamp"\t\t"1700000000"
\t}
\t"76561198087654321"
\t{
\t\t"AccountName"\t\t"commendbot_two"
\t\t"PersonaName"\t\t"two"
\t\t"RememberPassword"\t\t"0"
\t\t"MostRecent"\t\t"0"
\t\t"Timestamp"\t\t"1700000100"
\t}
\t"76561198099999999"
\t{
\t\t"AccountName"\t\t"Spare Account"
\t\t"PersonaName"\t\t"three"
\t\t"MostRecent"\t\t"0"
\t}
}
"""


def test_login_users_path_points_at_the_config_directory():
    assert login_users_path(Path("/steam")) == Path("/steam/config/loginusers.vdf")


def test_parse_login_users_maps_every_account_to_its_id64():
    assert parse_login_users(LOGINUSERS_VDF) == {
        "commendbot_one": 76561198012345678,
        "commendbot_two": 76561198087654321,
        "spare account": 76561198099999999,
    }


def test_parse_login_users_lower_cases_the_account_name():
    assert "commendbot_one" in parse_login_users(LOGINUSERS_VDF)
    assert "CommendBot_One" not in parse_login_users(LOGINUSERS_VDF)


def test_parse_login_users_returns_empty_for_a_file_without_a_users_block():
    assert parse_login_users('"config"\n{\n\t"a"\t\t"b"\n}\n') == {}


def test_parse_login_users_skips_an_entry_without_an_account_name():
    text = '"users"\n{\n\t"76561198012345678"\n\t{\n\t\t"PersonaName"\t\t"one"\n\t}\n}\n'
    assert parse_login_users(text) == {}


def test_parse_login_users_skips_a_non_numeric_key():
    text = '"users"\n{\n\t"notanid"\n\t{\n\t\t"AccountName"\t\t"one"\n\t}\n}\n'
    assert parse_login_users(text) == {}


def test_find_steam_id_by_account_ignores_case_and_surrounding_space():
    assert find_steam_id_by_account(LOGINUSERS_VDF, "  COMMENDBOT_TWO ") == 76561198087654321


def test_find_steam_id_by_account_returns_none_for_an_unknown_account():
    assert find_steam_id_by_account(LOGINUSERS_VDF, "never_logged_in") is None


def test_minimal_vdf_nests_blocks_under_their_key():
    parsed = _minimal_vdf(LOGINUSERS_VDF)
    assert set(parsed) == {"users"}
    assert parsed["users"]["76561198012345678"]["PersonaName"] == "one"


def test_minimal_vdf_ignores_comment_lines():
    text = '// a comment\n"users"\n{\n\t"1"\t\t"2"\n}\n'
    assert _minimal_vdf(text) == {"users": {"1": "2"}}


def test_minimal_vdf_tolerates_an_unbalanced_closing_brace():
    assert _minimal_vdf('}\n"a"\t"b"\n') == {"a": "b"}
