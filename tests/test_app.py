import asyncio

from roborock_homekit import app
from roborock_homekit.config import parse_config
from roborock_homekit.homekit import pairing

from .fakes import FakeVacuumClient


async def test_build_driver_persists_pairing(tmp_path):
    config = parse_config(
        {
            "roborock": {"email": "me@example.com"},
            "homekit": {"state_dir": str(tmp_path), "pincode": "031-45-154", "port": 51998},
        }
    )
    loop = asyncio.get_running_loop()
    driver = app.build_driver(config, FakeVacuumClient(), loop)

    info = pairing.read(config.pairing_file)
    assert info.pincode == "031-45-154"
    assert driver.state.pincode == b"031-45-154"
    assert driver.state.setup_id == info.setup_id
    assert info.setup_uri.startswith("X-HM://") and info.setup_uri.endswith(info.setup_id)

    # A restart keeps the same setup id (so the printed QR code stays valid).
    driver2 = app.build_driver(config, FakeVacuumClient(), loop)
    assert driver2.state.setup_id == info.setup_id
