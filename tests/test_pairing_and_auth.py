import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from roborock.data import UserData

from roborock_homekit.homekit import pairing
from roborock_homekit.vacuum import auth

USER_DATA = {
    "uid": 1,
    "token": "secret",
    "rruid": "rr",
    "region": "eu",
    "rriot": {
        "u": "u",
        "s": "s",
        "h": "h",
        "k": "k",
        "r": {"r": "EU", "a": "https://api", "m": "ssl://mqtt", "l": "https://wood"},
    },
}


# ---- pairing -----------------------------------------------------------------


def test_pairing_created_once_and_reused(tmp_path):
    path = tmp_path / "pairing.json"
    first = pairing.load_or_create(path, None)
    second = pairing.load_or_create(path, None)
    assert first == second
    assert len(first.pincode) == 10 and first.pincode[3] == "-"


def test_configured_pincode_wins(tmp_path):
    path = tmp_path / "pairing.json"
    pairing.load_or_create(path, None)
    info = pairing.load_or_create(path, "031-45-154")
    assert info.pincode == "031-45-154"
    assert pairing.read(path).pincode == "031-45-154"


def test_is_paired(tmp_path):
    state = tmp_path / "accessory.state"
    assert pairing.is_paired(state) is False
    state.write_text(json.dumps({"paired_clients": {"abc": "00"}}))
    assert pairing.is_paired(state) is True


def test_render_qr():
    assert len(pairing.render_qr("X-HM://0023ABCDEFGH").splitlines()) > 10


# ---- auth --------------------------------------------------------------------


async def test_interactive_login():
    api = SimpleNamespace(
        request_code=AsyncMock(),
        code_login=AsyncMock(return_value=UserData.from_dict(USER_DATA)),
    )

    async def base_url():
        return "https://euiot.roborock.com"

    api.base_url = base_url()
    prompts = []
    params = await auth.interactive_login(
        "me@example.com",
        prompt=lambda msg: prompts.append(msg) or " 123456 ",
        api_factory=lambda email: api,
    )
    api.code_login.assert_awaited_once_with("123456")
    assert "me@example.com" in prompts[0]
    assert params.username == "me@example.com"
    assert params.base_url == "https://euiot.roborock.com"


def test_credentials_round_trip(tmp_path):
    path = tmp_path / "sub" / "creds.json"
    params = auth.UserParams(
        username="me@example.com", user_data=UserData.from_dict(USER_DATA), base_url="https://x"
    )
    auth.save_credentials(path, params)
    loaded = auth.load_credentials(path, expected_email="ME@example.com")
    assert loaded.user_data.token == "secret"
    assert loaded.user_data.rriot.r.m == "ssl://mqtt"
    assert loaded.base_url == "https://x"
    if sys.platform != "win32":
        assert os.stat(path).st_mode & 0o777 == 0o600


def test_missing_credentials(tmp_path):
    with pytest.raises(auth.NotLoggedInError, match="login"):
        auth.load_credentials(tmp_path / "none.json")


def test_credentials_for_other_account(tmp_path):
    path = tmp_path / "creds.json"
    params = auth.UserParams(username="a@x.com", user_data=UserData.from_dict(USER_DATA))
    auth.save_credentials(path, params)
    with pytest.raises(auth.NotLoggedInError, match=r"b@x.com"):
        auth.load_credentials(path, expected_email="b@x.com")
