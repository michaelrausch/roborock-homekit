"""HomeKit pairing details (PIN code and QR setup URI).

HAP-python generates a new random PIN and setup id on every start unless told
otherwise. We persist them in ``pairing.json`` so the code stays the same across
restarts and so ``roborock-homekit pairing-info`` can show it over SSH at any time.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from pyhap import util


@dataclass(frozen=True)
class PairingInfo:
    pincode: str
    setup_id: str
    setup_uri: str | None = None
    """X-HM:// URI encoded in the QR code (written once the accessory exists)."""


def load_or_create(path: Path, configured_pincode: str | None) -> PairingInfo:
    """Return persisted pairing details, creating them on first run.

    A pincode set in the config always wins over a stored one.
    """
    stored = read(path)
    pincode = configured_pincode or (stored.pincode if stored else None)
    pincode = pincode or util.generate_pincode().decode()
    setup_id = stored.setup_id if stored else util.generate_setup_id()
    info = PairingInfo(pincode=pincode, setup_id=setup_id)
    if info != stored:
        write(path, info)
    return info


def read(path: Path) -> PairingInfo | None:
    try:
        return PairingInfo(**json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None


def write(path: Path, info: PairingInfo) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(info), indent=2), encoding="utf-8")


def is_paired(accessory_state_file: Path) -> bool:
    """Whether any iPhone/iPad has paired, according to HAP-python's state file."""
    try:
        state = json.loads(accessory_state_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return bool(state.get("paired_clients"))


def render_qr(setup_uri: str) -> str:
    """Render the setup URI as a QR code made of text, for the terminal."""
    import pyqrcode  # optional dependency, installed via HAP-python[QRCode]

    return pyqrcode.create(setup_uri).terminal(quiet_zone=2)
