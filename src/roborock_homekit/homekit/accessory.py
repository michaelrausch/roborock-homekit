"""The HomeKit accessory that represents the vacuum.

Apple Home has no robot-vacuum tile over HAP, so (like the popular homebridge
plugins) the vacuum is shown as:

* **Fan** (primary tile): on = cleaning, off = return to dock (or pause),
  speed = suction level.
* **Battery**: level, charging, low-battery warning.
* **Occupancy sensor "Docked"** (optional): detected while in the dock.
* **Switch "Find"** (optional): momentary, makes the vacuum announce itself.
* **Switch "Pause"** (optional): on = paused, off = resume.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pyhap import util
from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_FAN

from ..config import FeaturesConfig
from ..vacuum.client import VacuumClient
from ..vacuum.model import Activity, VacuumState
from . import mapping

_LOGGER = logging.getLogger(__name__)

FIND_ME_RESET_SECONDS = 1.0
# After a command, ignore contradicting status for this long so the tile does
# not flicker while the vacuum is still reacting.
COMMAND_GRACE_SECONDS = 15.0


class VacuumAccessory(Accessory):
    category = CATEGORY_FAN

    def __init__(
        self,
        driver: Any,
        name: str,
        client: VacuumClient,
        features: FeaturesConfig,
        poll_interval: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(driver, name)
        self._client = client
        self._features = features
        self._poll_interval = poll_interval
        self._clock = clock
        self._levels = client.fan_levels
        self._hold_on_until = 0.0
        self._unsubscribe: Callable[[], None] | None = None
        self._background: set[asyncio.Task[Any]] = set()

        self.set_info_service(
            manufacturer="Roborock", model=client.model, serial_number=client.serial
        )
        self._build_fan()
        self._build_battery()
        self._build_optional_services()

    # ---- service setup ------------------------------------------------

    def _build_fan(self) -> None:
        chars = ["Name", "RotationSpeed"] if self._levels else ["Name"]
        fan = self.add_preload_service("Fan", chars=chars)
        fan.configure_char("Name", value=self.display_name)
        self.char_on = fan.configure_char("On", setter_callback=self._set_on)
        self.char_speed = None
        if self._levels:
            self.char_speed = fan.configure_char(
                "RotationSpeed",
                properties={"minStep": mapping.speed_step(self._levels)},
                setter_callback=self._set_speed,
            )
        self.set_primary_service(fan)

    def _build_battery(self) -> None:
        battery = self.add_preload_service("BatteryService")
        self.char_battery = battery.configure_char("BatteryLevel")
        self.char_charging = battery.configure_char("ChargingState")
        self.char_low_battery = battery.configure_char("StatusLowBattery")

    def _build_optional_services(self) -> None:
        self.char_docked = None
        self.char_find = None
        self.char_pause = None
        if self._features.docked_sensor:
            sensor = self.add_preload_service("OccupancySensor", chars=["Name"])
            sensor.configure_char("Name", value="Docked")
            self.char_docked = sensor.configure_char("OccupancyDetected")
        if self._features.find_me_switch:
            self.char_find = self._add_switch("Find", "find", self._set_find)
        if self._features.pause_switch:
            self.char_pause = self._add_switch("Pause", "pause", self._set_pause)

    def _add_switch(self, label: str, unique_id: str, callback: Callable[[Any], None]) -> Any:
        switch = self.add_preload_service("Switch", chars=["Name"], unique_id=unique_id)
        switch.configure_char("Name", value=label)
        return switch.configure_char("On", setter_callback=callback)

    # ---- lifecycle (called by HAP-python's driver) -----------------------

    async def run(self) -> None:
        self._unsubscribe = self._client.add_listener(self.update_state)
        while True:
            await self.poll()
            if await util.event_wait(self.driver.aio_stop_event, self._poll_interval):
                break

    async def stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        await super().stop()

    async def poll(self) -> None:
        try:
            state = await self._client.refresh()
        except Exception as err:  # network hiccups must never kill the service
            _LOGGER.warning("Could not refresh vacuum status: %s", err)
            return
        self.update_state(state)

    # ---- vacuum -> HomeKit ------------------------------------------------

    def update_state(self, state: VacuumState) -> None:
        """Push a vacuum state to all HomeKit characteristics."""
        _LOGGER.debug("State: %s", state)
        if self._clock() >= self._hold_on_until:
            self.char_on.set_value(state.is_cleaning)
        if self.char_speed is not None:
            percent = mapping.level_to_percent(state.fan_level, self._levels)
            if percent is not None:
                self.char_speed.set_value(percent)
        self.char_battery.set_value(state.battery)
        self.char_charging.set_value(mapping.charging_state(state))
        self.char_low_battery.set_value(
            mapping.low_battery(state, self._features.low_battery_threshold)
        )
        if self.char_docked is not None:
            self.char_docked.set_value(1 if state.docked else 0)
        if self.char_pause is not None:
            self.char_pause.set_value(state.activity is Activity.PAUSED)

    # ---- HomeKit -> vacuum (setter callbacks run on the event loop) -------

    def _set_on(self, value: bool) -> None:
        self._hold_on_until = self._clock() + COMMAND_GRACE_SECONDS
        if value:
            if self._client.state.activity is Activity.PAUSED:
                self._dispatch("resume", self._client.resume)
            else:
                self._dispatch("start", self._client.start)
        elif self._features.fan_off_action == "pause":
            self._dispatch("pause", self._client.pause)
        else:
            self._dispatch("dock", self._client.dock)

    def _set_speed(self, percent: float) -> None:
        level = mapping.percent_to_level(percent, self._levels)
        if level is None:  # 0 % is HomeKit's way of turning the fan off; On handles that.
            return
        self._dispatch(f"set suction {level}", lambda: self._client.set_fan_level(level))

    def _set_find(self, value: bool) -> None:
        if not value:
            return
        self._dispatch("find me", self._client.find_me)
        self.driver.loop.call_later(FIND_ME_RESET_SECONDS, self.char_find.set_value, False)

    def _set_pause(self, value: bool) -> None:
        if value:
            self._dispatch("pause", self._client.pause)
        else:
            self._dispatch("resume", self._client.resume)

    def _dispatch(self, description: str, command: Callable[[], Awaitable[None]]) -> None:
        """Run a vacuum command in the background, logging (not raising) failures."""

        async def runner() -> None:
            _LOGGER.info("HomeKit requested: %s", description)
            try:
                await command()
            except Exception as err:
                _LOGGER.error("Command %r failed: %s", description, err)
                self._hold_on_until = 0.0
                self.update_state(self._client.state)

        task = asyncio.ensure_future(runner(), loop=self.driver.loop)
        # Keep a reference so the task isn't garbage-collected mid-flight.
        self._background.add(task)
        task.add_done_callback(self._background.discard)
