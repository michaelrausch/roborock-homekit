import json

import pytest

from roborock_homekit import cli
from roborock_homekit.homekit import pairing


@pytest.fixture
def config_file(tmp_path):
    state = tmp_path / "state"
    path = tmp_path / "config.toml"
    path.write_text(
        f'[roborock]\nemail = "me@example.com"\n[homekit]\nstate_dir = "{state.as_posix()}"\n'
    )
    return path, state


def test_parser_requires_command():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


@pytest.mark.parametrize("command", ["login", "devices", "status", "run", "pairing-info"])
def test_parser_accepts_commands(command):
    assert cli.build_parser().parse_args(["-c", "x.toml", command]).command == command


def test_config_error_exit_code(tmp_path, capsys):
    assert cli.main(["-c", str(tmp_path / "missing.toml"), "status"]) == 2
    assert "Config error" in capsys.readouterr().err


def test_status_without_login(config_file, capsys):
    path, _ = config_file
    assert cli.main(["-c", str(path), "status"]) == 1
    assert "roborock-homekit login" in capsys.readouterr().err


def test_pairing_info_before_first_run(config_file, capsys):
    path, _ = config_file
    assert cli.main(["-c", str(path), "pairing-info"]) == 1
    assert "Start the service" in capsys.readouterr().out


def test_pairing_info_shows_code(config_file, capsys):
    path, state = config_file
    pairing.write(
        state / "pairing.json",
        pairing.PairingInfo(pincode="031-45-154", setup_id="ABCD", setup_uri="X-HM://0023ABCD"),
    )
    (state / "accessory.state").write_text(json.dumps({"paired_clients": {}}))
    assert cli.main(["-c", str(path), "pairing-info"]) == 0
    out = capsys.readouterr().out
    assert "031-45-154" in out
    assert "Already paired" not in out
