"""Wires everything together and runs the HomeKit bridge.

    config -> Roborock client -> VacuumAccessory -> HAP-python driver

Everything runs on one asyncio event loop: python-roborock is asyncio-native
and HAP-python accepts an existing loop, so no threads are involved.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from dataclasses import replace

from pyhap.accessory_driver import AccessoryDriver

from .config import Config
from .homekit import pairing
from .homekit.accessory import VacuumAccessory
from .vacuum.auth import load_credentials
from .vacuum.client import VacuumClient
from .vacuum.roborock_client import RoborockVacuumClient

_LOGGER = logging.getLogger(__name__)


async def connect_vacuum(config: Config) -> VacuumClient:
    """Connect to the configured vacuum using the saved login."""
    user_params = load_credentials(config.credentials_file, expected_email=config.roborock.email)
    client = await RoborockVacuumClient.connect(
        user_params,
        cache_file=config.device_cache_file,
        device_name=config.roborock.device_name,
    )
    await client.refresh()
    return client


def build_driver(
    config: Config, client: VacuumClient, loop: asyncio.AbstractEventLoop
) -> AccessoryDriver:
    """Create the HAP driver and the vacuum accessory."""
    info = pairing.load_or_create(config.pairing_file, config.homekit.pincode)
    driver = AccessoryDriver(
        port=config.homekit.port,
        persist_file=str(config.accessory_state_file),
        pincode=info.pincode.encode(),
        loop=loop,
    )
    driver.state.setup_id = info.setup_id
    accessory = VacuumAccessory(
        driver,
        config.homekit.name,
        client,
        config.features,
        poll_interval=config.roborock.poll_interval_seconds,
    )
    driver.add_accessory(accessory)
    pairing.write(config.pairing_file, replace(info, setup_uri=accessory.xhm_uri()))
    return driver


async def run(config: Config) -> None:
    """Run until SIGINT/SIGTERM."""
    config.homekit.state_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not available on Windows
            loop.add_signal_handler(sig, stop.set)

    client = await connect_vacuum(config)
    _LOGGER.info("Connected to %s: %s", client.name, client.state)
    driver = build_driver(config, client, loop)
    try:
        await driver.async_start()
        if not driver.state.paired:
            _LOGGER.info(
                "Not paired yet. Run 'roborock-homekit pairing-info' to see the QR code, "
                "or add the accessory in Apple Home with code %s",
                driver.state.pincode.decode(),
            )
        await stop.wait()
        _LOGGER.info("Shutting down")
    finally:
        await driver.async_stop()
        await client.close()
