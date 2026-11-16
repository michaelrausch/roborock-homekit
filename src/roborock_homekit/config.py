"""Configuration loading and validation.

The configuration lives in a single TOML file (see ``config.example.toml``).
Every option has a sensible default except ``roborock.email``. Unknown keys are
rejected so that typos surface immediately instead of being silently ignored.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("/etc/roborock-homekit/config.toml")
CONFIG_ENV_VAR = "ROBOROCK_HOMEKIT_CONFIG"

_PINCODE_RE = re.compile(r"^\d{3}-\d{2}-\d{3}$")
# Codes Apple rejects as too easy to guess.
_FORBIDDEN_PINCODES = {
    "000-00-000", "111-11-111", "222-22-222", "333-33-333", "444-44-444",
    "555-55-555", "666-66-666", "777-77-777", "888-88-888", "999-99-999",
    "123-45-678", "876-54-321",
}  # fmt: skip
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
FAN_OFF_ACTIONS = ("dock", "pause")


class ConfigError(ValueError):
    """Raised when the configuration file is missing or invalid."""


@dataclass(frozen=True)
class RoborockConfig:
    email: str
    """Email address of your Roborock app account."""
    device_name: str | None = None
    """Name of the vacuum (as shown in the Roborock app). Optional with one vacuum."""
    poll_interval_seconds: int = 30
    """How often to poll the vacuum for status (push updates also arrive in between)."""


@dataclass(frozen=True)
class HomeKitConfig:
    name: str = "Roborock"
    """Name of the accessory as it first appears in Apple Home."""
    port: int = 51826
    """TCP port the HomeKit server listens on."""
    pincode: str | None = None
    """Pairing code in the form 123-45-678. Generated and saved on first run if omitted."""
    state_dir: Path = Path("/var/lib/roborock-homekit")
    """Where credentials, pairing state and caches are stored."""


@dataclass(frozen=True)
class FeaturesConfig:
    docked_sensor: bool = True
    """Expose an occupancy sensor that is 'detected' while the vacuum is in its dock."""
    find_me_switch: bool = True
    """Expose a switch that makes the vacuum say 'I'm here'."""
    pause_switch: bool = False
    """Expose a switch that pauses / resumes cleaning."""
    fan_off_action: str = "dock"
    """What turning the fan tile off does: 'dock' (return to dock) or 'pause'."""
    low_battery_threshold: int = 20
    """Battery percentage at or below which HomeKit shows a low-battery warning."""


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"


@dataclass(frozen=True)
class Config:
    roborock: RoborockConfig
    homekit: HomeKitConfig = field(default_factory=HomeKitConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    # Files inside state_dir. Kept here so every component agrees on locations.
    @property
    def credentials_file(self) -> Path:
        return self.homekit.state_dir / "roborock-credentials.json"

    @property
    def device_cache_file(self) -> Path:
        return self.homekit.state_dir / "roborock-cache.pickle"

    @property
    def accessory_state_file(self) -> Path:
        return self.homekit.state_dir / "accessory.state"

    @property
    def pairing_file(self) -> Path:
        return self.homekit.state_dir / "pairing.json"


def resolve_config_path(cli_path: str | os.PathLike[str] | None = None) -> Path:
    """Pick the config path: CLI flag, then environment variable, then default."""
    if cli_path:
        return Path(cli_path)
    if env_path := os.environ.get(CONFIG_ENV_VAR):
        return Path(env_path)
    return DEFAULT_CONFIG_PATH


def load_config(path: str | os.PathLike[str]) -> Config:
    """Read and validate the TOML config at ``path``."""
    path = Path(path)
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(
            f"Config file not found: {path}. Copy config.example.toml there and edit it."
        ) from None
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"{path} is not valid TOML: {err}") from None
    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> Config:
    """Build a validated :class:`Config` from an already-parsed TOML dict."""
    _reject_unknown(raw, {f.name for f in fields(Config)}, where="top level")

    roborock_raw = _section(raw, "roborock")
    if not roborock_raw.get("email"):
        raise ConfigError("[roborock] email is required")

    config = Config(
        roborock=_build(RoborockConfig, roborock_raw, "roborock"),
        homekit=_build(HomeKitConfig, _section(raw, "homekit"), "homekit"),
        features=_build(FeaturesConfig, _section(raw, "features"), "features"),
        logging=_build(LoggingConfig, _section(raw, "logging"), "logging"),
    )
    _validate(config)
    return config


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table/section")
    return value


def _reject_unknown(raw: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(
            f"Unknown option(s) in {where}: {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )


def _build(cls: type, raw: dict[str, Any], section: str) -> Any:
    """Instantiate a section dataclass, checking keys and basic types."""
    cls_fields = {f.name: f for f in fields(cls)}
    _reject_unknown(raw, set(cls_fields), where=f"[{section}]")
    kwargs: dict[str, Any] = {}
    for name, value in raw.items():
        default = cls_fields[name].default
        if isinstance(default, Path):
            value = Path(value)
        elif isinstance(default, bool):
            if not isinstance(value, bool):
                raise ConfigError(f"[{section}] {name} must be true or false")
        elif isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigError(f"[{section}] {name} must be a whole number")
        elif not isinstance(value, str):
            raise ConfigError(f"[{section}] {name} must be a string")
        kwargs[name] = value
    return cls(**kwargs)


def _validate(config: Config) -> None:
    if config.roborock.poll_interval_seconds < 5:
        raise ConfigError("[roborock] poll_interval_seconds must be at least 5")
    if not 1 <= config.homekit.port <= 65535:
        raise ConfigError("[homekit] port must be between 1 and 65535")
    pincode = config.homekit.pincode
    if pincode is not None:
        if not _PINCODE_RE.match(pincode):
            raise ConfigError("[homekit] pincode must look like 123-45-678")
        if pincode in _FORBIDDEN_PINCODES:
            raise ConfigError("[homekit] pincode is too simple; HomeKit will reject it")
    if config.features.fan_off_action not in FAN_OFF_ACTIONS:
        raise ConfigError(f"[features] fan_off_action must be one of {FAN_OFF_ACTIONS}")
    if not 0 <= config.features.low_battery_threshold <= 100:
        raise ConfigError("[features] low_battery_threshold must be between 0 and 100")
    if config.logging.level.upper() not in _LOG_LEVELS:
        raise ConfigError(f"[logging] level must be one of {sorted(_LOG_LEVELS)}")
