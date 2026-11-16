"""Roborock account login and credential storage.

Login is a one-off interactive step (``roborock-homekit login``): Roborock emails
a one-time code, you type it in, and the resulting session token is saved as
JSON (readable only by the service user). The service then reuses it.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from roborock.data import UserData
from roborock.devices.device_manager import UserParams
from roborock.web_api import RoborockApiClient

_LOGGER = logging.getLogger(__name__)


class NotLoggedInError(RuntimeError):
    """Raised when no saved Roborock credentials exist."""


async def interactive_login(
    email: str,
    prompt: Callable[[str], str] = input,
    api_factory: Callable[[str], Any] = lambda email: RoborockApiClient(username=email),
) -> UserParams:
    """Request an emailed code, ask for it via ``prompt`` and return the session."""
    api = api_factory(email)
    await api.request_code()
    code = prompt(f"Enter the code Roborock emailed to {email}: ").strip()
    user_data = await api.code_login(code)
    base_url = await api.base_url
    return UserParams(username=email, user_data=user_data, base_url=base_url)


def save_credentials(path: Path, params: UserParams) -> None:
    """Write credentials as JSON with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "username": params.username,
        "base_url": params.base_url,
        "user_data": params.user_data.as_dict(),
    }
    # Create with 0600 from the start so the token is never world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    _LOGGER.info("Saved Roborock credentials to %s", path)


def load_credentials(path: Path, expected_email: str | None = None) -> UserParams:
    """Load credentials saved by :func:`save_credentials`."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NotLoggedInError(
            f"No Roborock credentials at {path}. Run 'roborock-homekit login' first."
        ) from None
    if expected_email and payload["username"].lower() != expected_email.lower():
        raise NotLoggedInError(
            f"Saved credentials are for {payload['username']}, but the config says "
            f"{expected_email}. Run 'roborock-homekit login' again."
        )
    return UserParams(
        username=payload["username"],
        user_data=UserData.from_dict(payload["user_data"]),
        base_url=payload.get("base_url"),
    )
