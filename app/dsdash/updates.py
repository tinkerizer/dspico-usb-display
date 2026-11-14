"""Looks on GitHub for a newer release, once a day. Nothing is sent but the request itself, and
nothing is downloaded: the editor only shows a link to the release."""
import json
import logging
import re
import threading
import urllib.request
from typing import Optional

from .version import VERSION

log = logging.getLogger(__name__)

LATEST = "https://api.github.com/repos/tinkerizer/dspico-usb-display/releases/latest"
RELEASES = "https://github.com/tinkerizer/dspico-usb-display/releases/"
DAY = 86400
FIRST_CHECK_SECONDS = 20    # After starting, so it never slows the DS coming up


def parse(version) -> Optional[tuple]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version) if isinstance(version, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def newer(release: dict, current: str) -> Optional[dict]:
    """The release as {version, url} if it's newer than `current`. Anything unexpected gives None."""
    latest, mine, url = parse(release.get("tag_name")), parse(current), release.get("html_url")
    if not latest or not mine or latest <= mine or not isinstance(url, str) or not url.startswith(RELEASES):
        return None
    return {"version": ".".join(map(str, latest)), "url": url}


def fetch_latest() -> dict:
    request = urllib.request.Request(LATEST, headers={"Accept": "application/vnd.github+json", "User-Agent": "DS-Display"})
    with urllib.request.urlopen(request, timeout=10) as reply:
        return json.loads(reply.read(200_000))


class UpdateChecker(threading.Thread):
    def __init__(self):
        super().__init__(name="update-check", daemon=True)
        self.found: Optional[dict] = None
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        wait = FIRST_CHECK_SECONDS
        while not self._stop_event.wait(wait):
            try:
                self.found = newer(fetch_latest(), VERSION)
                log.info("Update check: %s", f"{self.found['version']} is out" if self.found else "up to date")
            except (OSError, ValueError, AttributeError) as error:    # Offline, or GitHub said something else
                log.info("Update check failed: %s", error)
            wait = DAY
