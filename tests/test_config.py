from pathlib import Path

import pytest

from roborock_homekit.config import (
    CONFIG_ENV_VAR,
    DEFAULT_CONFIG_PATH,
    ConfigError,
    load_config,
    parse_config,
    resolve_config_path,
)

EXAMPLE = Path(__file__).resolve().parent.parent / "config.example.toml"


def test_minimal_config_uses_defaults():
    config = parse_config({"roborock": {"email": "a@b.c"}})
    assert config.roborock.email == "a@b.c"
    assert config.roborock.poll_interval_seconds == 30
    assert config.homekit.port == 51826
    assert config.homekit.pincode is None
    assert config.features.docked_sensor is True
    assert config.features.pause_switch is False
    assert config.features.fan_off_action == "dock"
    assert config.credentials_file == Path("/var/lib/roborock-homekit/roborock-credentials.json")


def test_example_config_is_valid():
    config = load_config(EXAMPLE)
    assert config.homekit.name == "Roborock"


def test_state_dir_becomes_path():
    config = parse_config({"roborock": {"email": "x"}, "homekit": {"state_dir": "/tmp/s"}})
    assert config.homekit.state_dir == Path("/tmp/s")
    assert config.pairing_file == Path("/tmp/s/pairing.json")


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({}, "email is required"),
        ({"roborock": {"email": "x", "emial": "y"}}, "Unknown option"),
        ({"roborock": {"email": "x"}, "extra": {}}, "Unknown option"),
        ({"roborock": {"email": "x", "poll_interval_seconds": 1}}, "at least 5"),
        ({"roborock": {"email": "x", "poll_interval_seconds": "30"}}, "whole number"),
        ({"roborock": {"email": "x"}, "homekit": {"port": 0}}, "port"),
        ({"roborock": {"email": "x"}, "homekit": {"pincode": "1234"}}, "123-45-678"),
        ({"roborock": {"email": "x"}, "homekit": {"pincode": "111-11-111"}}, "too simple"),
        ({"roborock": {"email": "x"}, "features": {"docked_sensor": "yes"}}, "true or false"),
        ({"roborock": {"email": "x"}, "features": {"fan_off_action": "stop"}}, "fan_off_action"),
        ({"roborock": {"email": "x"}, "features": {"low_battery_threshold": 101}}, "between"),
        ({"roborock": {"email": "x"}, "logging": {"level": "LOUD"}}, "level"),
        ({"roborock": "x"}, "must be a table"),
    ],
)
def test_invalid_config_is_rejected(raw, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(raw)


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_bad_toml(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("[roborock\n")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(path)


def test_resolve_config_path_precedence(monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    assert resolve_config_path() == DEFAULT_CONFIG_PATH
    monkeypatch.setenv(CONFIG_ENV_VAR, "/env/config.toml")
    assert resolve_config_path() == Path("/env/config.toml")
    assert resolve_config_path("/cli/config.toml") == Path("/cli/config.toml")
