"""The interface the HomeKit layer uses to talk to a vacuum.

Keeping this as a small Protocol means the HomeKit code can be tested with a
fake, and the Roborock-specific code stays in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .model import VacuumState


class VacuumClient(Protocol):
    @property
    def name(self) -> str:
        """Display name of the vacuum."""

    @property
    def model(self) -> str:
        """Model identifier, e.g. 'roborock.vacuum.a15'."""

    @property
    def serial(self) -> str:
        """Unique device id."""

    @property
    def fan_levels(self) -> list[str]:
        """Suction levels from weakest to strongest, e.g. ['quiet', 'balanced', 'turbo', 'max']."""

    @property
    def state(self) -> VacuumState:
        """The most recently known state (does not do any I/O)."""

    async def refresh(self) -> VacuumState:
        """Fetch the latest state from the vacuum."""

    def add_listener(self, callback: Callable[[VacuumState], None]) -> Callable[[], None]:
        """Call ``callback`` whenever the vacuum pushes a new state. Returns an unsubscribe fn."""

    async def start(self) -> None: ...

    async def pause(self) -> None: ...

    async def resume(self) -> None: ...

    async def dock(self) -> None: ...

    async def set_fan_level(self, level: str) -> None: ...

    async def find_me(self) -> None: ...

    async def close(self) -> None: ...
