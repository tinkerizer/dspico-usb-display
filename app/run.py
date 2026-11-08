#!/usr/bin/env python3
"""Starts the DS display service. Run with Windows Python, which owns the USB device."""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dsdash.app import App
from dsdash.server import serve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-device", action="store_true",
                        help="Leave the DS alone, to work on the web UI next to the installed app")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = App()
    if args.no_device:
        app.device.start = app.firmware.start = lambda: None
    app.start()
    try:
        serve(app, args.port)
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
