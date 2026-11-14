"""Keeps the DS on the bundled build, once the user has agreed to the update.

A push is quick but only lives in RAM, so a build that's new to the SD card is then also
copied there, once, to survive a power cycle. That takes the DS off USB for a few seconds.
"""
import json
import logging
import struct
import sys
import threading
import time
import zlib
from pathlib import Path
from typing import Optional

from . import layout as layouts

try:
    import dsctl
except ImportError:     # Running from the repo. The packaged app bundles it.
    sys.path.insert(0, str(layouts.ROOT.parent / "tools"))
    import dsctl

log = logging.getLogger(__name__)

CHECK_SECONDS = 15
RETRY_SECONDS = 300     # Between pushes, so a build that won't stick can't loop.
SD_RECORD = layouts.LOCAL_DIR / "firmware.json"     # What's on the SD card, as {crc, build}


def rom_path() -> Optional[Path]:
    for path in (layouts.ASSETS / "usb-display.nds", layouts.ROOT.parent / "ds" / "usb-display.nds"):
        if path.exists():
            return path
    return None


def rom_crc(rom: bytes) -> int:
    arm9, arm7 = dsctl.parse_nds(rom)
    return zlib.crc32(arm9["data"] + arm7["data"])


def sd_record() -> dict:
    try:
        return json.loads(SD_RECORD.read_text())
    except (OSError, ValueError):
        return {}


def running_build(link):
    """The DS's boot CRC and build number. Early builds' replies are too short to say."""
    reply = link.request(dsctl.OP_PING)
    if len(reply) < 28:
        return None, "from the SD card"
    fields = struct.unpack("<7I", reply)
    return fields[1], fields[6]


class FirmwareKeeper(threading.Thread):
    def __init__(self):
        super().__init__(name="ds-firmware", daemon=True)
        self.state = "Waiting for the DS"
        self.offer = None           # {"running": build} while an update waits for a yes or no
        self._allowed = None        # The answer, for this run
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._next_push = 0.0
        self._failed_install = None

    def stop(self):
        self._stop_event.set()
        self._wake.set()

    def answer(self, update: bool):
        """The user's yes or no to the update on offer. A no lasts until the app is restarted."""
        self._allowed, self.offer = bool(update), None
        self._wake.set()

    def _report(self, state: str):
        if state != self.state:
            log.info("Firmware: %s", state)
        self.state = state

    def check(self, link, rom: bytes):
        """One look at the DS, pushing if it's behind and a push is due.

        Returns the running build if the SD card needs it too. The caller installs it
        after closing the dev port.
        """
        wanted = rom_crc(rom)
        crc, build = running_build(link)
        record = sd_record()
        on_sd = record.get("crc") == wanted
        # After a power cycle the boot CRC means nothing, but the build number still does.
        if crc == wanted or (on_sd and build == record.get("build")):
            self._next_push = 0.0
            self.offer = None
            self._report(f"Current: build {build}")
            return None if on_sd or self._failed_install == wanted else build
        if self._allowed is None:
            self.offer = {"running": build}
            self._report(f"Update ready: the DS is on build {build}")
        elif not self._allowed:
            self._report(f"Out of date: build {build}, update skipped")
        elif time.monotonic() < self._next_push:
            self._report(f"Out of date: build {build}, will retry")
        else:
            self._next_push = time.monotonic() + RETRY_SECONDS
            log.info("Firmware: pushing %08x over build %s", wanted, build)
            dsctl.upload_and_boot(link, rom)
            self._report("Pushed, waiting for it to restart")
        return None

    def install(self, rom: bytes, filename: str, build):
        """Copies the running build to the SD card. A failure isn't retried until the next run."""
        wanted = rom_crc(rom)
        self._report("Copying to the SD card")
        try:
            target = dsctl.install_on_sd(rom, filename)
        except Exception as error:
            self._failed_install = wanted
            self._report(f"Not copied to the SD card: {error}")
            return
        SD_RECORD.parent.mkdir(parents=True, exist_ok=True)
        SD_RECORD.write_text(json.dumps({"crc": wanted, "build": build}))
        self._report(f"Copied build {build} to {target}")

    def run(self):
        path = rom_path()
        if not path:
            self._report("No build to push")
            return
        rom = path.read_bytes()
        while not self._stop_event.is_set():
            try:
                with dsctl.open_dev_port(0) as port:
                    build = self.check(dsctl.Link(port, on_log=lambda text: None), rom)
                if build is not None:
                    self.install(rom, path.name, build)
            except Exception as error:   # No DS, dev tools using the port, or a bad reply
                self._report(f"Not checked: {error}")
            self._wake.wait(CHECK_SECONDS)
            self._wake.clear()
