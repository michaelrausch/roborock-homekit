"""Logging configuration.

Logs go to stderr; under systemd they end up in the journal
(``journalctl -u roborock-homekit``), which adds its own timestamps.
"""

from __future__ import annotations

import logging
import os
import sys


def setup_logging(level: str = "INFO") -> None:
    under_systemd = "INVOCATION_ID" in os.environ
    fmt = "%(levelname)s %(name)s: %(message)s"
    if not under_systemd:
        fmt = "%(asctime)s " + fmt
    logging.basicConfig(level=level.upper(), format=fmt, stream=sys.stderr, force=True)
    # These libraries are chatty at INFO; keep them quieter unless debugging.
    if level.upper() != "DEBUG":
        for noisy in ("pyhap", "roborock", "aiomqtt"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
