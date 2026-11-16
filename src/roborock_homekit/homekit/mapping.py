"""Pure functions translating between vacuum concepts and HomeKit values.

HomeKit's Fan service has a RotationSpeed of 0-100 %. We split that range into
equal steps, one per suction level, so e.g. with four levels:

    quiet = 25 %, balanced = 50 %, turbo = 75 %, max = 100 %
"""

from __future__ import annotations

import math

from ..vacuum.model import VacuumState

# HomeKit enum values.
CHARGING_STATE_NOT_CHARGING = 0
CHARGING_STATE_CHARGING = 1
LOW_BATTERY_NORMAL = 0
LOW_BATTERY_LOW = 1


def speed_step(levels: list[str]) -> float:
    """Size of one fan step in percent (used as the characteristic's minStep)."""
    return 100 / len(levels) if levels else 1


def level_to_percent(level: str | None, levels: list[str]) -> int | None:
    """Percentage for a suction level, or None if the level isn't in the list."""
    if level is None or level not in levels:
        return None
    return round((levels.index(level) + 1) * 100 / len(levels))


def percent_to_level(percent: float, levels: list[str]) -> str | None:
    """Suction level for a percentage. 0 % (fan off) returns None."""
    if not levels or percent <= 0:
        return None
    index = math.ceil(min(percent, 100) * len(levels) / 100) - 1
    return levels[max(index, 0)]


def charging_state(state: VacuumState) -> int:
    return CHARGING_STATE_CHARGING if state.charging else CHARGING_STATE_NOT_CHARGING


def low_battery(state: VacuumState, threshold: int) -> int:
    return LOW_BATTERY_LOW if state.battery <= threshold else LOW_BATTERY_NORMAL
