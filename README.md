# roborock-homekit

Control your Roborock vacuum from Apple Home, using a small Python service that
runs happily on a Raspberry Pi Zero W (no Node.js / Homebridge needed).

## What you get in Apple Home

HomeKit has no robot-vacuum tile (that's Matter-only), so the vacuum appears the
same way the popular Homebridge plugins show it:

| Tile / control | What it does |
|---|---|
| **Fan** (main tile) | On = start cleaning (or resume if paused). Off = return to dock (configurable: pause). |
| Fan **speed** | Suction level: quiet / balanced / turbo / max (/ max+ if your model has it). |
| **Battery** | Level, charging state, low-battery warning. |
| **Docked** sensor | "Occupancy detected" while the vacuum is in its dock. Handy for automations. *(optional)* |
| **Find** switch | Makes the vacuum say "I'm here". Turns itself back off. *(optional)* |
| **Pause** switch | On = pause, off = resume. *(optional, off by default)* |

It talks to the vacuum locally over your Wi-Fi when it can, and falls back to
Roborock's cloud. It works with V1-protocol vacuums, which covers the S and Q
series (S5/S6/S7/S8, Q5/Q7/Q8 and so on).

## Requirements

- Raspberry Pi (Zero W or newer) running **Raspberry Pi OS Bookworm** (Python 3.11).
- The Pi on the same network as your iPhone / Home hub.
- Your Roborock app account email.

## Install (over SSH)

**1. Copy the project to the Pi.** From your PC, either:

```bash
scp -r roborock-homekit pi@raspberrypi.local:~
```

or, if the repo is on GitHub, on the Pi run `git clone <your repo url> ~/roborock-homekit`.

**2. SSH in and run the installer:**

```bash
ssh pi@raspberrypi.local
cd ~/roborock-homekit
sudo ./scripts/install.sh
```

The installer:

- creates a `roborock-homekit` system user
- creates a virtualenv in `/opt/roborock-homekit`
- installs only prebuilt wheels from piwheels, so nothing is compiled on the Pi. This takes about 10 minutes on a Zero W.
- copies the config to `/etc/roborock-homekit/config.toml`
- installs a systemd service and enables it at boot

**3. Configure, log in, start:**

```bash
sudo nano /etc/roborock-homekit/config.toml   # set your Roborock email
roborock-homekit login                        # Roborock emails you a code; type it in
roborock-homekit status                       # check it can see your vacuum
sudo systemctl start roborock-homekit
roborock-homekit pairing-info                 # shows QR code + 8-digit code
```

**4. Pair:** in the Home app, tap **+ → Add Accessory**, then scan the QR code
shown in your terminal or choose **More options** and enter the code. Accept
the "uncertified accessory" prompt.

## Everyday commands

```bash
roborock-homekit status                     # battery, state, suction, errors
journalctl -u roborock-homekit -f           # live logs
sudo systemctl restart roborock-homekit     # after editing the config
```

All commands: `login`, `devices`, `status`, `run`, `pairing-info`. Add `-v`
for debug output, or `-c path/to/config.toml` to use another config file.

**Upgrade:** copy or `git pull` the new code, then run `sudo ./scripts/install.sh` again.
Your config, login and pairing are kept.

**Uninstall:** run `sudo ./scripts/uninstall.sh`. Add `--purge` to also delete the config and state.

## Configuration

Everything lives in `/etc/roborock-homekit/config.toml`. Every option is
commented in [config.example.toml](config.example.toml). The main ones:

| Option | Default | Meaning |
|---|---|---|
| `roborock.email` | *(required)* | Roborock app account. |
| `roborock.device_name` | only vacuum | Which vacuum, if you have several (`roborock-homekit devices`). |
| `roborock.poll_interval_seconds` | `30` | Status poll interval. Push updates also arrive in between. |
| `homekit.name` | `Roborock` | Accessory name. |
| `homekit.port` | `51826` | HomeKit TCP port. |
| `homekit.pincode` | random, saved | Pairing code `123-45-678`. |
| `features.docked_sensor` | `true` | Show the Docked sensor. |
| `features.find_me_switch` | `true` | Show the Find switch. |
| `features.pause_switch` | `false` | Show the Pause switch. |
| `features.fan_off_action` | `dock` | `dock` or `pause` when the tile is turned off. |
| `features.low_battery_threshold` | `20` | Low-battery warning at or below this %. |
| `logging.level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

Unknown or misspelled options are rejected with a clear error, so typos never fail silently.

Changing which optional tiles are shown changes the accessory's layout. If
Home doesn't pick the change up, remove the accessory in the Home app and pair
again (see below).

## Troubleshooting

- **"No Roborock credentials"**: run `roborock-homekit login`.
- **Login code never arrives**: check the email matches your Roborock app login.
  Roborock rate-limits code requests, so wait a few minutes and retry.
- **Accessory not found when pairing**: the iPhone and Pi must be on the same
  network or VLAN, because pairing uses mDNS (Bonjour). Check the logs, and that
  nothing else is using port 51826.
- **Re-pair from scratch**: remove the accessory in the Home app, then run:
  ```bash
  sudo systemctl stop roborock-homekit
  sudo rm /var/lib/roborock-homekit/accessory.state
  sudo systemctl start roborock-homekit
  ```
- **Tile shows "No Response"**: check `journalctl -u roborock-homekit`. The service
  restarts itself on failure, and it retries every 30 s after boot until the
  network is up.

## How it works / development

```
config.toml ──> app.py ──> RoborockVacuumClient ──(python-roborock)──> vacuum
                   │                ▲
                   ▼                │ VacuumClient protocol
             VacuumAccessory ───────┘
                   │
              HAP-python driver ──(HomeKit)──> Apple Home
```

| File | Role |
|---|---|
| `src/roborock_homekit/config.py` | Typed config dataclasses, TOML loading and validation. |
| `vacuum/model.py` | `VacuumState` / `Activity`. Plain data with no library types. |
| `vacuum/client.py` | The `VacuumClient` protocol that the HomeKit side depends on. |
| `vacuum/roborock_client.py` | The only python-roborock-specific code (state mapping, commands). |
| `vacuum/auth.py` | Email-code login and credential storage (JSON, mode 0600). |
| `homekit/mapping.py` | Pure functions for suction ↔ fan %, battery and charging values. |
| `homekit/accessory.py` | The HomeKit services and their callbacks. |
| `homekit/pairing.py` | Persistent PIN / setup id and the terminal QR code. |
| `app.py`, `cli.py` | Wiring and the command line. |

Everything runs on a single asyncio event loop, with no threads.

Run the tests on any machine (no vacuum or Pi needed):

```bash
python -m venv .venv
.venv/bin/pip install -e .[dev]     # Windows: .venv\Scripts\pip ...
pytest
ruff check . && ruff format --check .
```

`requirements-pi.txt` pins every dependency to a version that has an armv6l
wheel. Its header shows how to check a new set of versions before deploying.
