from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from roborock import RoborockCommand
from roborock.data import RoborockDockState, RoborockErrorCode, RoborockStateCode
from roborock.data.v1.v1_clean_modes import VacuumModes

from roborock_homekit.vacuum.model import Activity
from roborock_homekit.vacuum.roborock_client import (
    RoborockVacuumClient,
    select_device,
    suction_levels,
    translate_status,
)

S7_MODES = [
    VacuumModes.QUIET,
    VacuumModes.BALANCED,
    VacuumModes.TURBO,
    VacuumModes.MAX,
    VacuumModes.GENTLE,
]


def make_status(**kw):
    defaults = {
        "state": RoborockStateCode.charging,
        "battery": 80,
        "error_code": RoborockErrorCode.none,
        "dock_state": RoborockDockState.charging,
        "fan_speed_name": "balanced",
        "fan_speed_options": S7_MODES,
    }
    return SimpleNamespace(**{**defaults, **kw})


# ---- translate_status ------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "activity"),
    [
        (RoborockStateCode.cleaning, Activity.CLEANING),
        (RoborockStateCode.segment_cleaning, Activity.CLEANING),
        (RoborockStateCode.zoned_mopping, Activity.CLEANING),
        (RoborockStateCode.returning_home, Activity.RETURNING),
        (RoborockStateCode.charging, Activity.DOCKED),
        (RoborockStateCode.charging_complete, Activity.DOCKED),
        (RoborockStateCode.emptying_the_bin, Activity.DOCKED),
        (RoborockStateCode.paused, Activity.PAUSED),
        (RoborockStateCode.idle, Activity.IDLE),
        (RoborockStateCode.error, Activity.ERROR),
        (RoborockStateCode.updating, Activity.UNKNOWN),
        (None, Activity.UNKNOWN),
    ],
)
def test_activity_mapping(code, activity):
    assert translate_status(make_status(state=code)).activity is activity


def test_charging_and_docked():
    state = translate_status(make_status())
    assert state.charging and state.docked and state.battery == 80


def test_full_battery_is_docked_but_not_charging():
    state = translate_status(make_status(dock_state=RoborockDockState.full, battery=100))
    assert state.docked and not state.charging


def test_away_from_dock():
    state = translate_status(
        make_status(state=RoborockStateCode.cleaning, dock_state=RoborockDockState.idle)
    )
    assert not state.docked and not state.charging and state.is_cleaning


def test_error_is_reported():
    state = translate_status(make_status(error_code=RoborockErrorCode.bumper_stuck, state=None))
    assert state.error == "bumper_stuck"
    assert state.activity is Activity.ERROR


def test_non_suction_fan_mode_is_hidden():
    assert translate_status(make_status(fan_speed_name="gentle")).fan_level is None


def test_missing_battery_is_zero():
    assert translate_status(make_status(battery=None)).battery == 0


def test_suction_levels_keep_order_and_skip_mop_modes():
    assert suction_levels(make_status()) == ["quiet", "balanced", "turbo", "max"]
    with_plus = make_status(fan_speed_options=[*S7_MODES, VacuumModes.MAX_PLUS])
    assert suction_levels(with_plus)[-1] == "max_plus"


# ---- RoborockVacuumClient ----------------------------------------------------


def make_device(name="Robo", status=None, v1=True):
    status = status or make_status()
    status.refresh = AsyncMock()
    status.add_update_listener = lambda cb: setattr(status, "listener", cb) or (lambda: None)
    props = SimpleNamespace(status=status, command=SimpleNamespace(send=AsyncMock()))
    return SimpleNamespace(
        name=name,
        duid=f"duid-{name}",
        product=SimpleNamespace(model="roborock.vacuum.a15"),
        v1_properties=props if v1 else None,
    )


@pytest.mark.parametrize(
    ("method", "args", "command", "params"),
    [
        ("start", (), RoborockCommand.APP_START, None),
        ("pause", (), RoborockCommand.APP_PAUSE, None),
        ("resume", (), RoborockCommand.APP_START, None),
        ("dock", (), RoborockCommand.APP_CHARGE, None),
        ("set_fan_level", ("turbo",), RoborockCommand.SET_CUSTOM_MODE, [103]),
    ],
)
async def test_commands(method, args, command, params):
    device = make_device()
    client = RoborockVacuumClient(device)
    await getattr(client, method)(*args)
    device.v1_properties.command.send.assert_awaited_once_with(command, params)
    device.v1_properties.status.refresh.assert_awaited()  # state refreshed after command


async def test_find_me():
    device = make_device()
    await RoborockVacuumClient(device).find_me()
    device.v1_properties.command.send.assert_awaited_once_with(RoborockCommand.FIND_ME)


async def test_unsupported_fan_level_raises():
    with pytest.raises(ValueError, match="Unsupported fan level"):
        await RoborockVacuumClient(make_device()).set_fan_level("ludicrous")


async def test_refresh_and_properties():
    client = RoborockVacuumClient(make_device())
    state = await client.refresh()
    assert state.activity is Activity.DOCKED
    assert client.state == state
    assert client.serial == "duid-Robo"
    assert client.fan_levels == ["quiet", "balanced", "turbo", "max"]


def test_push_updates_reach_listener():
    device = make_device()
    client = RoborockVacuumClient(device)
    received = []
    client.add_listener(received.append)
    device.v1_properties.status.state = RoborockStateCode.cleaning
    device.v1_properties.status.listener()
    assert received[-1].activity is Activity.CLEANING


def test_non_v1_device_rejected():
    with pytest.raises(ValueError, match="not a supported"):
        RoborockVacuumClient(make_device(v1=False))


# ---- select_device -----------------------------------------------------------


def test_select_only_vacuum():
    device = make_device()
    assert select_device([device, make_device("Mop", v1=False)], None) is device


def test_select_by_name_case_insensitive():
    a, b = make_device("Upstairs"), make_device("Downstairs")
    assert select_device([a, b], "downstairs") is b


@pytest.mark.parametrize(
    ("devices", "name", "message"),
    [
        ([], None, "No supported"),
        ([make_device("A"), make_device("B")], None, "set \\[roborock\\] device_name"),
        ([make_device("A")], "Z", "No vacuum named 'Z'"),
    ],
)
def test_select_errors(devices, name, message):
    with pytest.raises(LookupError, match=message):
        select_device(devices, name)
