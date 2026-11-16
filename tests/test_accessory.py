import asyncio

import pytest
from pyhap.accessory_driver import AccessoryDriver

from roborock_homekit.config import FeaturesConfig
from roborock_homekit.homekit import accessory as accessory_module
from roborock_homekit.homekit.accessory import VacuumAccessory
from roborock_homekit.vacuum.model import Activity

from .fakes import FakeVacuumClient


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def driver(tmp_path):
    drv = AccessoryDriver(
        address="127.0.0.1",
        port=51999,
        persist_file=str(tmp_path / "accessory.state"),
        loop=asyncio.get_running_loop(),
    )
    yield drv


def make(driver, client=None, clock=None, **features):
    client = client or FakeVacuumClient()
    acc = VacuumAccessory(
        driver,
        "Roborock",
        client,
        FeaturesConfig(**features),
        poll_interval=30,
        clock=clock or Clock(),
    )
    return acc, client


async def settle():
    """Let background command tasks run."""
    for _ in range(5):
        await asyncio.sleep(0)


def service_names(acc):
    return [s.display_name for s in acc.services]


async def test_default_services(driver):
    acc, _ = make(driver)
    names = service_names(acc)
    assert {"Fan", "BatteryService", "OccupancySensor", "Switch"} <= set(names)
    assert names.count("Switch") == 1  # find-me only; pause is off by default


async def test_optional_services_can_be_disabled(driver):
    acc, _ = make(driver, docked_sensor=False, find_me_switch=False)
    assert "OccupancySensor" not in service_names(acc)
    assert "Switch" not in service_names(acc)


async def test_pause_switch_enabled(driver):
    acc, _ = make(driver, pause_switch=True)
    assert service_names(acc).count("Switch") == 2


async def test_fan_step_matches_levels(driver):
    acc, _ = make(driver)
    assert acc.char_speed.properties["minStep"] == 25


async def test_no_speed_when_no_levels(driver):
    acc, _ = make(driver, FakeVacuumClient(levels=[]))
    assert acc.char_speed is None


async def test_update_state_sets_characteristics(driver):
    acc, client = make(driver)
    client.set_state(
        activity=Activity.CLEANING, battery=15, charging=False, docked=False, fan_level="turbo"
    )
    acc.update_state(client.state)
    assert acc.char_on.value is True
    assert acc.char_speed.value == 75
    assert acc.char_battery.value == 15
    assert acc.char_charging.value == 0
    assert acc.char_low_battery.value == 1
    assert acc.char_docked.value == 0


async def test_poll_refreshes(driver):
    acc, client = make(driver)
    client.set_state(battery=42)
    await acc.poll()
    assert acc.char_battery.value == 42


async def test_poll_survives_errors(driver):
    acc, client = make(driver, FakeVacuumClient(fail_with=ConnectionError("offline")))
    await acc.poll()  # must not raise
    assert client.commands == []


async def test_push_updates_via_listener(driver):
    acc, client = make(driver)
    acc._unsubscribe = client.add_listener(acc.update_state)
    client.push(battery=33)
    assert acc.char_battery.value == 33


async def test_turn_on_starts_cleaning(driver):
    acc, client = make(driver)
    acc.char_on.client_update_value(True)
    await settle()
    assert client.commands == [("start",)]


async def test_turn_on_while_paused_resumes(driver):
    acc, client = make(driver)
    client.set_state(activity=Activity.PAUSED)
    acc.char_on.client_update_value(True)
    await settle()
    assert client.commands == [("resume",)]


async def test_turn_off_docks_by_default(driver):
    acc, client = make(driver)
    acc.char_on.set_value(True)
    acc.char_on.client_update_value(False)
    await settle()
    assert client.commands == [("dock",)]


async def test_turn_off_can_pause(driver):
    acc, client = make(driver, fan_off_action="pause")
    acc.char_on.set_value(True)
    acc.char_on.client_update_value(False)
    await settle()
    assert client.commands == [("pause",)]


async def test_speed_sets_fan_level(driver):
    acc, client = make(driver)
    acc.char_speed.client_update_value(100)
    await settle()
    assert client.commands == [("fan", "max")]


async def test_speed_zero_is_ignored(driver):
    acc, client = make(driver)
    acc.char_speed.client_update_value(0)
    await settle()
    assert client.commands == []


async def test_grace_period_prevents_flicker(driver):
    clock = Clock()
    acc, client = make(driver, clock=clock)
    acc.char_on.client_update_value(True)
    await settle()
    acc.update_state(client.state)  # vacuum still reports docked
    assert acc.char_on.value is True
    clock.now += accessory_module.COMMAND_GRACE_SECONDS + 1
    acc.update_state(client.state)
    assert acc.char_on.value is False


async def test_failed_command_reverts_tile(driver):
    acc, client = make(driver, FakeVacuumClient(fail_with=RuntimeError("boom")))
    acc.char_on.client_update_value(True)
    await settle()
    assert client.commands == [("start",)]
    assert acc.char_on.value is False


async def test_find_me_is_momentary(driver, monkeypatch):
    monkeypatch.setattr(accessory_module, "FIND_ME_RESET_SECONDS", 0)
    acc, client = make(driver)
    acc.char_find.client_update_value(True)
    await settle()
    await asyncio.sleep(0.01)
    assert client.commands == [("find_me",)]
    assert acc.char_find.value is False


async def test_pause_switch(driver):
    acc, client = make(driver, pause_switch=True)
    acc.char_pause.client_update_value(True)
    acc.char_pause.client_update_value(False)
    await settle()
    assert client.commands == [("pause",), ("resume",)]
    client.set_state(activity=Activity.PAUSED)
    acc.update_state(client.state)
    assert acc.char_pause.value is True
