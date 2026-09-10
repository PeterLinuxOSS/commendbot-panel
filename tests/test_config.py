import json

import pytest

from commendbot_panel.config import (
    ENV_IPC_TOKEN,
    ENV_MONGO_URI,
    ENV_SERVERS_FILE,
    ConfigError,
    JsonSettingsStore,
    UserSettings,
    from_mapping,
    load_settings,
    to_mapping,
)
from commendbot_panel.constants import DEFAULT_LAUNCH_ARGUMENTS
from commendbot_panel.servers import GameServer

URI = "mongodb://user:pw@localhost:27017/commendbot"


def test_load_settings_raises_without_a_mongo_uri(tmp_path):
    with pytest.raises(ConfigError, match=ENV_MONGO_URI):
        load_settings(store=JsonSettingsStore(tmp_path / "settings.json"), environ={})


def test_load_settings_treats_a_blank_mongo_uri_as_missing(tmp_path):
    with pytest.raises(ConfigError):
        load_settings(
            store=JsonSettingsStore(tmp_path / "settings.json"),
            environ={ENV_MONGO_URI: "   "},
        )


def test_load_settings_keeps_the_uri_from_the_environment(tmp_path):
    settings = load_settings(
        store=JsonSettingsStore(tmp_path / "settings.json"), environ={ENV_MONGO_URI: URI}
    )
    assert settings.mongo_uri == URI


def test_load_settings_generates_an_ipc_token_when_none_is_given(tmp_path):
    store = JsonSettingsStore(tmp_path / "settings.json")
    first = load_settings(store=store, environ={ENV_MONGO_URI: URI})
    second = load_settings(store=store, environ={ENV_MONGO_URI: URI})
    assert first.ipc_token and first.ipc_token != second.ipc_token


def test_load_settings_uses_the_ipc_token_from_the_environment(tmp_path):
    settings = load_settings(
        store=JsonSettingsStore(tmp_path / "settings.json"),
        environ={ENV_MONGO_URI: URI, ENV_IPC_TOKEN: " shared-token "},
    )
    assert settings.ipc_token == "shared-token"


def test_load_settings_has_an_empty_server_pool_without_a_servers_file(tmp_path):
    settings = load_settings(
        store=JsonSettingsStore(tmp_path / "settings.json"), environ={ENV_MONGO_URI: URI}
    )
    assert settings.servers == ()


def test_load_settings_loads_the_server_pool_named_by_the_environment(tmp_path):
    pool = tmp_path / "servers.json"
    pool.write_text(
        json.dumps([{"name": "One", "host": "a.example", "port": 27015}]),
        encoding="utf-8",
    )
    settings = load_settings(
        store=JsonSettingsStore(tmp_path / "settings.json"),
        environ={ENV_MONGO_URI: URI, ENV_SERVERS_FILE: str(pool)},
    )
    assert settings.servers == (GameServer("One", "a.example", 27015, ""),)


def test_load_settings_takes_the_user_settings_from_the_store(tmp_path):
    store = JsonSettingsStore(tmp_path / "settings.json")
    store.save(UserSettings(remembered_login="bot_one", auto_reconnect=True))
    settings = load_settings(store=store, environ={ENV_MONGO_URI: URI})
    assert settings.user.remembered_login == "bot_one"
    assert settings.user.auto_reconnect is True


def test_with_user_returns_a_copy_and_leaves_the_original_alone(tmp_path):
    settings = load_settings(
        store=JsonSettingsStore(tmp_path / "settings.json"), environ={ENV_MONGO_URI: URI}
    )
    updated = settings.with_user(UserSettings(remembered_login="bot_two"))
    assert updated.user.remembered_login == "bot_two"
    assert settings.user.remembered_login == ""
    assert updated.mongo_uri == settings.mongo_uri


def test_json_store_returns_defaults_when_the_file_does_not_exist(tmp_path):
    assert JsonSettingsStore(tmp_path / "missing.json").load() == UserSettings()


def test_json_store_round_trips_user_settings(tmp_path):
    store = JsonSettingsStore(tmp_path / "nested" / "settings.json")
    original = UserSettings(
        steam_path=tmp_path,
        csgo_path=tmp_path,
        launch_arguments="-novid",
        auto_reconnect=True,
        auto_start=True,
        end_task="Shutdown",
        remembered_login="bot_one",
    )
    store.save(original)
    assert store.load() == original


def test_json_store_creates_the_parent_directory(tmp_path):
    store = JsonSettingsStore(tmp_path / "a" / "b" / "settings.json")
    store.save(UserSettings())
    assert store.path.is_file()


def test_json_store_returns_defaults_for_a_corrupt_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    assert JsonSettingsStore(path).load() == UserSettings()


def test_json_store_drops_a_path_that_no_longer_exists(tmp_path):
    store = JsonSettingsStore(tmp_path / "settings.json")
    store.save(UserSettings(steam_path=tmp_path / "gone", csgo_path=tmp_path))
    loaded = store.load()
    assert loaded.steam_path is None
    assert loaded.csgo_path == tmp_path


def test_to_mapping_renders_a_missing_path_as_an_empty_string():
    assert to_mapping(UserSettings())["SteamPath"] == ""


def test_from_mapping_falls_back_to_the_default_launch_arguments():
    assert from_mapping({}).launch_arguments == DEFAULT_LAUNCH_ARGUMENTS
    assert from_mapping({}).end_task == "Do nothing"


# A1 — the registry hands back "0"/0, and bool("0") is True.
def test_from_mapping_reads_a_zero_flag_as_false():
    assert from_mapping({"autoreconnect": "0", "autostart": 0}).auto_reconnect is False
    assert from_mapping({"autoreconnect": "0", "autostart": 0}).auto_start is False


def test_from_mapping_reads_registry_dwords_and_strings_as_true():
    assert from_mapping({"autoreconnect": 1, "autostart": "true"}).auto_reconnect is True
    assert from_mapping({"autoreconnect": 1, "autostart": "true"}).auto_start is True


def test_paths_are_valid_only_when_both_directories_exist(tmp_path):
    assert UserSettings().paths_are_valid is False
    assert UserSettings(steam_path=tmp_path).paths_are_valid is False
    assert UserSettings(steam_path=tmp_path, csgo_path=tmp_path).paths_are_valid is True
    assert (
        UserSettings(steam_path=tmp_path, csgo_path=tmp_path / "gone").paths_are_valid
        is False
    )
