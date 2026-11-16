"""Command-line entry point: ``roborock-homekit <command>``.

Commands:
  login         Log in to your Roborock account (one-time, interactive).
  devices       List the vacuums on your account.
  status        Print the vacuum's current status.
  run           Run the HomeKit bridge (what the systemd service runs).
  pairing-info  Show the HomeKit pairing code and QR code.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from collections.abc import Callable, Sequence

from . import app
from .config import Config, ConfigError, load_config, resolve_config_path
from .homekit import pairing
from .logging_setup import setup_logging
from .vacuum.auth import NotLoggedInError, interactive_login, load_credentials, save_credentials

_LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roborock-homekit", description="Expose a Roborock vacuum to Apple HomeKit."
    )
    parser.add_argument(
        "-c",
        "--config",
        help="path to config.toml (default: $ROBOROCK_HOMEKIT_CONFIG or "
        "/etc/roborock-homekit/config.toml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")
    sub.add_parser("login", help="log in to your Roborock account (emails you a code)")
    sub.add_parser("devices", help="list vacuums on your account")
    sub.add_parser("status", help="print the vacuum's current status")
    sub.add_parser("run", help="run the HomeKit bridge")
    sub.add_parser("pairing-info", help="show the HomeKit pairing code / QR code")
    return parser


async def cmd_login(config: Config) -> int:
    params = await interactive_login(config.roborock.email)
    save_credentials(config.credentials_file, params)
    print(f"Logged in. Credentials saved to {config.credentials_file}")
    return 0


async def cmd_devices(config: Config) -> int:
    from roborock.devices.device_manager import create_device_manager

    manager = await create_device_manager(load_credentials(config.credentials_file))
    try:
        for device in await manager.get_devices():
            supported = "supported" if device.v1_properties is not None else "not supported"
            print(f"{device.name!r:30} model={device.product.model}  ({supported})")
    finally:
        await manager.close()
    return 0


async def cmd_status(config: Config) -> int:
    client = await app.connect_vacuum(config)
    try:
        state = client.state
        print(f"Vacuum:     {client.name} ({client.model})")
        print(f"Activity:   {state.activity.value}")
        print(f"Battery:    {state.battery}%{' (charging)' if state.charging else ''}")
        print(f"Docked:     {'yes' if state.docked else 'no'}")
        print(f"Suction:    {state.fan_level or 'n/a'}  (levels: {', '.join(client.fan_levels)})")
        print(f"Error:      {state.error or 'none'}")
    finally:
        await client.close()
    return 0


async def cmd_run(config: Config) -> int:
    await app.run(config)
    return 0


async def cmd_pairing_info(config: Config) -> int:
    info = pairing.read(config.pairing_file)
    if info is None or info.setup_uri is None:
        print("No pairing info yet. Start the service first: sudo systemctl start roborock-homekit")
        return 1
    if pairing.is_paired(config.accessory_state_file):
        print("Already paired with Apple Home. To re-pair, remove it in the Home app,")
        print(f"stop the service and delete {config.accessory_state_file}.")
    with contextlib.suppress(ImportError):
        print(pairing.render_qr(info.setup_uri))
    print(f"Scan the QR code in the Home app, or enter the code: {info.pincode}")
    return 0


COMMANDS: dict[str, Callable[[Config], object]] = {
    "login": cmd_login,
    "devices": cmd_devices,
    "status": cmd_status,
    "run": cmd_run,
    "pairing-info": cmd_pairing_info,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(resolve_config_path(args.config))
    except ConfigError as err:
        print(f"Config error: {err}", file=sys.stderr)
        return 2
    setup_logging("DEBUG" if args.verbose else config.logging.level)
    try:
        return asyncio.run(COMMANDS[args.command](config))
    except NotLoggedInError as err:
        print(err, file=sys.stderr)
        return 1
    except LookupError as err:  # device selection problems
        print(err, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
