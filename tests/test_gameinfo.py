from pathlib import Path

from commendbot_panel.steam.gameinfo import (
    GAMEINFO_TEMPLATE,
    console_log_path,
    gameinfo_path,
    render_gameinfo,
    write_gameinfo,
)

STEAM_ID = 76561198012345678


def test_gameinfo_path_is_under_the_csgo_subdirectory():
    assert gameinfo_path(Path("/games/csgo")) == Path("/games/csgo/csgo/gameinfo.txt")


def test_console_log_path_sits_next_to_gameinfo():
    assert console_log_path(Path("/games/csgo")) == Path("/games/csgo/csgo/console.log")


def test_the_template_still_carries_the_placeholder():
    assert "%ACCOUNT%" in GAMEINFO_TEMPLATE


def test_render_gameinfo_stamps_the_steam_id_into_the_game_field():
    assert f'game\t"{STEAM_ID}"' in render_gameinfo(STEAM_ID)


def test_render_gameinfo_leaves_no_placeholder_behind():
    assert "%ACCOUNT%" not in render_gameinfo(STEAM_ID)


def test_render_gameinfo_changes_nothing_else_in_the_template():
    rendered = render_gameinfo(STEAM_ID)
    assert rendered == GAMEINFO_TEMPLATE.replace("%ACCOUNT%", str(STEAM_ID))
    assert "SteamAppId\t\t\t\t730" in rendered


def test_render_gameinfo_gives_two_accounts_different_bodies():
    assert render_gameinfo(STEAM_ID) != render_gameinfo(STEAM_ID + 1)


def test_write_gameinfo_writes_the_rendered_body_and_returns_the_path(tmp_path):
    (tmp_path / "csgo").mkdir()
    written = write_gameinfo(tmp_path, STEAM_ID)
    assert written == tmp_path / "csgo" / "gameinfo.txt"
    assert written.read_text(encoding="utf-8") == render_gameinfo(STEAM_ID)


def test_write_gameinfo_overwrites_a_previous_stamp(tmp_path):
    (tmp_path / "csgo").mkdir()
    write_gameinfo(tmp_path, STEAM_ID)
    written = write_gameinfo(tmp_path, STEAM_ID + 1)
    assert str(STEAM_ID) not in written.read_text(encoding="utf-8")
