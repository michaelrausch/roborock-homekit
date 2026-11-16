"""Test doubles shared across tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from roborock_homekit.vacuum.model import Activity, VacuumState

DOCKED = VacuumState(
    activity=Activity.DOCKED, battery=100, charging=False, docked=True, fan_level="balanced"
)


class FakeVacuumClient:
    """In-memory VacuumClient that records the commands it receives."""

    def __init__(
        self,
        state: VacuumState = DOCKED,
        levels: list[str] | None = None,
        fail_with: Exception | None = None,
    ) -> None:
        self._state = state
        self._levels = levels if levels is not None else ["quiet", "balanced", "turbo", "max"]
        self.commands: list[tuple[str, ...]] = []
        self.listeners: list[Callable[[VacuumState], None]] = []
        self.fail_with = fail_with
        self.closed = False

    name = "Robo"
    model = "roborock.vacuum.a15"
    serial = "duid-123"

    @property
    def fan_levels(self) -> list[str]:
        return self._levels

    @property
    def state(self) -> VacuumState:
        return self._state

    def set_state(self, **changes: object) -> None:
        self._state = replace(self._state, **changes)

    def push(self, **changes: object) -> None:
        """Simulate the vacuum pushing a state change."""
        self.set_state(**changes)
        for listener in self.listeners:
            listener(self._state)

    async def refresh(self) -> VacuumState:
        if self.fail_with:
            raise self.fail_with
        return self._state

    def add_listener(self, callback: Callable[[VacuumState], None]) -> Callable[[], None]:
        self.listeners.append(callback)
        return lambda: self.listeners.remove(callback)

    async def _record(self, *command: str) -> None:
        self.commands.append(command)
        if self.fail_with:
            raise self.fail_with

    async def start(self) -> None:
        await self._record("start")

    async def pause(self) -> None:
        await self._record("pause")

    async def resume(self) -> None:
        await self._record("resume")

    async def dock(self) -> None:
        await self._record("dock")

    async def set_fan_level(self, level: str) -> None:
        await self._record("fan", level)

    async def find_me(self) -> None:
        await self._record("find_me")

    async def close(self) -> None:
        self.closed = True
