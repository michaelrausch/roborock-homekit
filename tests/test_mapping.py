import pytest

from roborock_homekit.homekit import mapping
from roborock_homekit.vacuum.model import Activity, VacuumState

FOUR = ["quiet", "balanced", "turbo", "max"]
FIVE = [*FOUR, "max_plus"]


@pytest.mark.parametrize(
    ("level", "levels", "expected"),
    [
        ("quiet", FOUR, 25),
        ("balanced", FOUR, 50),
        ("max", FOUR, 100),
        ("quiet", FIVE, 20),
        ("max_plus", FIVE, 100),
        ("gentle", FOUR, None),
        (None, FOUR, None),
    ],
)
def test_level_to_percent(level, levels, expected):
    assert mapping.level_to_percent(level, levels) == expected


@pytest.mark.parametrize(
    ("percent", "levels", "expected"),
    [
        (0, FOUR, None),
        (1, FOUR, "quiet"),
        (25, FOUR, "quiet"),
        (26, FOUR, "balanced"),
        (50, FOUR, "balanced"),
        (100, FOUR, "max"),
        (150, FOUR, "max"),
        (40, FIVE, "balanced"),
        (50, [], None),
    ],
)
def test_percent_to_level(percent, levels, expected):
    assert mapping.percent_to_level(percent, levels) == expected


@pytest.mark.parametrize("levels", [FOUR, FIVE])
def test_round_trip(levels):
    for level in levels:
        assert mapping.percent_to_level(mapping.level_to_percent(level, levels), levels) == level


def test_speed_step():
    assert mapping.speed_step(FOUR) == 25
    assert mapping.speed_step(FIVE) == 20
    assert mapping.speed_step([]) == 1


def _state(**kw):
    defaults = {"activity": Activity.DOCKED, "battery": 50, "charging": False, "docked": True}
    return VacuumState(**{**defaults, **kw})


def test_charging_state():
    assert mapping.charging_state(_state(charging=True)) == mapping.CHARGING_STATE_CHARGING
    assert mapping.charging_state(_state()) == mapping.CHARGING_STATE_NOT_CHARGING


def test_low_battery_threshold_is_inclusive():
    assert mapping.low_battery(_state(battery=20), 20) == mapping.LOW_BATTERY_LOW
    assert mapping.low_battery(_state(battery=21), 20) == mapping.LOW_BATTERY_NORMAL
