"""Library-independent description of what the vacuum is doing.

Nothing in this module knows about python-roborock or HomeKit. The Roborock
adapter translates into these types and the HomeKit layer reads from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Activity(Enum):
    """High-level activity, simplified from Roborock's many state codes."""

    CLEANING = "cleaning"
    RETURNING = "returning"
    DOCKED = "docked"
    PAUSED = "paused"
    IDLE = "idle"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class VacuumState:
    activity: Activity
    battery: int
    """Battery level, 0-100."""
    charging: bool
    docked: bool
    fan_level: str | None = None
    """Current suction level name, e.g. 'balanced'. None if unknown or not a suction level."""
    error: str | None = None
    """Human-readable error name, or None when there is no error."""

    @property
    def is_cleaning(self) -> bool:
        return self.activity is Activity.CLEANING


UNKNOWN_STATE = VacuumState(activity=Activity.UNKNOWN, battery=0, charging=False, docked=False)
