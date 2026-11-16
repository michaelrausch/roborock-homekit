"""Adapter from python-roborock to our :class:`VacuumClient` interface.

This is the only module that knows about python-roborock's device API. If the
library changes, this is the file to update.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roborock import RoborockCommand
from roborock.data import RoborockDockState, RoborockErrorCode, RoborockStateCode
from roborock.devices.device import RoborockDevice
from roborock.devices.device_manager import DeviceManager, UserParams, create_device_manager
from roborock.devices.file_cache import FileCache

from .model import UNKNOWN_STATE, Activity, VacuumState

_LOGGER = logging.getLogger(__name__)

# Suction levels we expose on the HomeKit fan, weakest to strongest. Mop-only
# and special modes (off, gentle, custom, smart_mode) are deliberately skipped
# because they don't map onto a "fan speed".
SUCTION_LEVELS = ("quiet", "balanced", "turbo", "max", "max_plus")

_S = RoborockStateCode
_ACTIVITY_BY_STATE: dict[RoborockStateCode, Activity] = {
    **dict.fromkeys(
        (
            _S.starting, _S.cleaning, _S.spot_cleaning, _S.zoned_cleaning,
            _S.segment_cleaning, _S.going_to_target, _S.remote_control_active,
            _S.manual_mode, _S.mapping, _S.patrol,
            _S.robot_status_mopping, _S.clean_mop_cleaning, _S.clean_mop_mopping,
            _S.segment_mopping, _S.segment_clean_mop_cleaning, _S.segment_clean_mop_mopping,
            _S.zoned_mopping, _S.zoned_clean_mop_cleaning, _S.zoned_clean_mop_mopping,
        ),
        Activity.CLEANING,
    ),
    **dict.fromkeys(
        (_S.returning_home, _S.docking, _S.going_to_wash_the_mop, _S.back_to_dock_washing_duster),
        Activity.RETURNING,
    ),
    **dict.fromkeys(
        (
            _S.charging, _S.charging_complete, _S.emptying_the_bin,
            _S.washing_the_mop, _S.washing_the_mop_2, _S.air_drying_stopping,
        ),
        Activity.DOCKED,
    ),
    _S.paused: Activity.PAUSED,
    _S.idle: Activity.IDLE,
    _S.charger_disconnected: Activity.IDLE,
    _S.error: Activity.ERROR,
    _S.charging_problem: Activity.ERROR,
}  # fmt: skip

_DOCKED_STATES = {
    RoborockDockState.charging,
    RoborockDockState.full,
    RoborockDockState.off_peak_waiting,
    RoborockDockState.dusting,
}


def translate_status(status: Any) -> VacuumState:
    """Convert a python-roborock StatusTrait into a :class:`VacuumState`.

    ``status`` is duck-typed so tests can pass a simple namespace with the
    attributes ``state``, ``battery``, ``error_code``, ``dock_state`` and
    ``fan_speed_name``.
    """
    dock_state = status.dock_state
    activity = _ACTIVITY_BY_STATE.get(status.state, Activity.UNKNOWN)
    error_code = status.error_code
    has_error = error_code is not None and error_code != RoborockErrorCode.none
    if has_error and activity is Activity.UNKNOWN:
        activity = Activity.ERROR
    fan = status.fan_speed_name
    return VacuumState(
        activity=activity,
        battery=max(0, min(100, status.battery or 0)),
        charging=dock_state == RoborockDockState.charging,
        docked=dock_state in _DOCKED_STATES,
        fan_level=fan if fan in SUCTION_LEVELS else None,
        error=error_code.name if has_error else None,
    )


def suction_levels(status: Any) -> list[str]:
    """Ordered suction level names this particular vacuum supports."""
    supported = {mode.value for mode in status.fan_speed_options}
    return [level for level in SUCTION_LEVELS if level in supported]


class RoborockVacuumClient:
    """A single Roborock vacuum, implementing :class:`VacuumClient`."""

    def __init__(self, device: RoborockDevice, manager: DeviceManager | None = None) -> None:
        if device.v1_properties is None:
            raise ValueError(
                f"{device.name} is not a supported (V1 protocol) Roborock vacuum. "
                "S-series and Q-series vacuums are supported."
            )
        self._device = device
        self._manager = manager
        self._props = device.v1_properties
        self._state = UNKNOWN_STATE

    # ---- construction -------------------------------------------------

    @classmethod
    async def connect(
        cls,
        user_params: UserParams,
        cache_file: Path,
        device_name: str | None = None,
    ) -> RoborockVacuumClient:
        """Log in with saved credentials and pick the configured vacuum."""
        manager = await create_device_manager(user_params, cache=FileCache(cache_file))
        devices = await manager.get_devices()
        try:
            device = select_device(devices, device_name)
        except Exception:
            await manager.close()
            raise
        _LOGGER.info("Using vacuum %r (%s)", device.name, device.product.model)
        return cls(device, manager)

    # ---- VacuumClient interface --------------------------------------

    @property
    def name(self) -> str:
        return self._device.name

    @property
    def model(self) -> str:
        return self._device.product.model

    @property
    def serial(self) -> str:
        return self._device.duid

    @property
    def fan_levels(self) -> list[str]:
        return suction_levels(self._props.status)

    @property
    def state(self) -> VacuumState:
        return self._state

    async def refresh(self) -> VacuumState:
        await self._props.status.refresh()
        self._state = translate_status(self._props.status)
        return self._state

    def add_listener(self, callback: Callable[[VacuumState], None]) -> Callable[[], None]:
        def on_update() -> None:
            self._state = translate_status(self._props.status)
            callback(self._state)

        return self._props.status.add_update_listener(on_update)

    async def start(self) -> None:
        await self._send(RoborockCommand.APP_START)

    async def pause(self) -> None:
        await self._send(RoborockCommand.APP_PAUSE)

    async def resume(self) -> None:
        # Roborock resumes a paused clean with the same command that starts one.
        await self._send(RoborockCommand.APP_START)

    async def dock(self) -> None:
        await self._send(RoborockCommand.APP_CHARGE)

    async def set_fan_level(self, level: str) -> None:
        codes = {mode.value: mode.code for mode in self._props.status.fan_speed_options}
        if level not in codes:
            raise ValueError(f"Unsupported fan level {level!r}; supported: {sorted(codes)}")
        await self._send(RoborockCommand.SET_CUSTOM_MODE, [codes[level]])

    async def find_me(self) -> None:
        await self._props.command.send(RoborockCommand.FIND_ME)

    async def close(self) -> None:
        if self._manager is not None:
            await self._manager.close()

    # ---- helpers -------------------------------------------------------

    async def _send(self, command: RoborockCommand, params: Any = None) -> None:
        _LOGGER.info("Sending %s %s", command.value, params or "")
        await self._props.command.send(command, params)
        # Raw commands don't update traits, so refresh to reflect the change quickly.
        await self.refresh()


def select_device(devices: list[RoborockDevice], device_name: str | None) -> RoborockDevice:
    """Pick the vacuum to expose: by name if given, otherwise the only V1 vacuum."""
    vacuums = [d for d in devices if d.v1_properties is not None]
    if device_name:
        for device in vacuums:
            if device.name.casefold() == device_name.casefold():
                return device
        names = ", ".join(repr(d.name) for d in vacuums) or "none"
        raise LookupError(f"No vacuum named {device_name!r}. Found: {names}")
    if not vacuums:
        raise LookupError("No supported Roborock vacuums found on this account")
    if len(vacuums) > 1:
        names = ", ".join(repr(d.name) for d in vacuums)
        raise LookupError(f"Several vacuums found ({names}); set [roborock] device_name")
    return vacuums[0]
