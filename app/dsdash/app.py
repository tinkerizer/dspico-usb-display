"""Ties the pieces together: read sensors, render, hand frames to the device."""
import logging
import struct
import threading
import time
from datetime import datetime
from io import BytesIO
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image

from . import codec, layout as layouts, themes, widgets
from .device import Animation, DsDevice
from .firmware import FirmwareKeeper
from .sensors import Sensors
from .version import VERSION

log = logging.getLogger(__name__)


class LayoutConflict(Exception):
    """The save was based on a layout that has since changed."""


class App:
    def __init__(self):
        self.device = DsDevice()
        self.firmware = FirmwareKeeper()
        self.themes = themes.ThemeStore()
        self.sensors = Sensors()
        self.layout = self.themes.layout
        # Starts from the clock so it keeps rising when the app restarts, which
        # stops a tab left open from matching a revision it never saw.
        self.revision = time.time_ns() // 1_000_000
        self.brightness = 100
        self._frame = Image.new("RGB", (256, 384))
        self._frame_id = 0          # Goes up when the picture changes, so the editor only fetches new ones
        self._frame_pixels = None
        self._frame_png = (-1, b"")
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._render_now = threading.Event()
        self._animation_key = None
        self._ticked = threading.Condition()
        self._ticks = 0
        self._pictures = {}         # Theme thumbnails, by name
        self._sleep_box = (None, None)

    def start(self):
        self.device.start()
        self.firmware.start()
        self._load_animations()
        threading.Thread(target=self._tick_loop, name="ds-render", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._render_now.set()
        with self._ticked:
            self._ticked.notify_all()
        self.device.stop()
        self.firmware.stop()

    def set_layout(self, new_layout: dict, revision: Optional[int] = None) -> Tuple[dict, int]:
        """Saves unless revision is given and out of date. Returns the layout and its revision."""
        clean = layouts.validate(new_layout)
        with self._lock:
            if revision is not None and revision != self.revision:
                raise LayoutConflict("Another tab changed the layout")
            self.themes.save_layout(clean)
            self.layout = clean
            self.revision += 1
            saved = self.revision
            self._load_animations()
        self._render_now.set()
        return clean, saved

    def change_theme(self, request: dict) -> dict:
        """Previews, uses, saves or deletes a theme, then redraws."""
        action, name = request.get("action"), request.get("name")
        with self._lock:
            if action == "preview":
                self.themes.preview = themes.clean(request.get("theme") or {})
            elif action == "use":
                self.themes.use(name)
            elif action == "save":
                self.themes.save(name, request.get("theme") or {})
            elif action == "delete":
                self.themes.delete(name)
            elif action == "sleep":
                self.themes.set_sleep(request.get("sleep"))
            elif action == "colours":
                self.themes.set_colours(request.get("theme") or {})
            elif action == "import":
                self.themes.import_zip(request["zip"])
            else:
                raise ValueError("Unknown theme action")
            if action not in ("preview", "sleep", "colours"):
                # Each theme has its own layout, so the editor reloads it.
                self.layout = self.themes.layout
                self.revision += 1
            self._load_animations()
        self._render_now.set()
        return self.theme_listing()

    def theme_listing(self) -> dict:
        """The themes, and where the sleep screen's GIF goes, for the editor to preview it."""
        listing = self.themes.listing()
        sleep = listing["sleep"]
        key = (sleep["file"], sleep["screen"], str(layouts.ART_DIR))
        if self._sleep_box[0] != key:
            box = None
            if sleep["file"]:
                try:
                    box = codec.sleep_box(str(layouts.resolve_file(sleep["file"])), sleep["screen"])
                except (OSError, ValueError):
                    pass
            self._sleep_box = (key, box)
        listing["sleepBox"] = self._sleep_box[1]
        return listing

    def theme_picture(self, name: str) -> bytes:
        """A theme drawn at half size, for its card. Kept until the theme changes."""
        folder = self.themes.folders().get(name)
        if folder is None:
            raise ValueError("No theme with that name")
        key = (str(folder), (folder / "theme.json").stat().st_mtime_ns)
        if self._pictures.get(name, (None,))[0] != key:
            with layouts.art_folder(folder):
                theme = themes.read(folder)
                themed = themes.apply_layout(themes.read_layout(folder), theme)
                frame = themes.apply_tone(widgets.render(themed, self.sensors.stats, datetime.now()), themed, theme)
                widgets.draw_animations(frame, themed)
            out = BytesIO()
            frame.resize((128, 192), Image.BOX).save(out, "PNG")
            self._pictures[name] = (key, out.getvalue())
        return self._pictures[name][1]

    def wait_for_tick(self, seen: int, timeout: float) -> int:
        """Waits for the next drawing after `seen`, for the editor's live updates."""
        with self._ticked:
            self._ticked.wait_for(lambda: self._ticks != seen or self._stop.is_set(), timeout)
            return self._ticks

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def reset_layout(self, revision: Optional[int] = None) -> Tuple[dict, int]:
        return self.set_layout(layouts.default_layout(), revision)

    def _load_animations(self):
        """Re-encodes only when something that affects the animations changed."""
        theme = self.themes.active
        themed = themes.apply_layout(self.layout, theme)
        elements = [e for e in themed["elements"] if e["type"] == "animation" and not e["hidden"]]
        sleep = self.themes.sleep
        key = repr((elements, sleep, layouts.ART_DIR))     # A GIF from art: comes from the theme's folder
        if key == self._animation_key:
            return
        self._animation_key = key

        animations: List[Animation] = []
        for element in elements:
            rect = (element["x"], element["y"], element["w"], element["h"])
            try:
                props = element["props"]
                path = layouts.resolve_file(props["file"])
                crop = (props["crop_x"], props["crop_y"], props["crop_w"], props["crop_h"])
                area, frames = codec.encode_animation(str(path), rect, crop if crop[2] and crop[3] else None)
                animations.append(Animation(area, frames))
            except (OSError, ValueError, struct.error) as error:
                log.warning("Skipping animation %s: %s", element["id"], error)
        sleep_animation = None
        if sleep["file"]:
            try:
                area, frames = codec.encode_sleep(str(layouts.resolve_file(sleep["file"])), sleep["screen"])
                sleep_animation = Animation(area, frames)
            except (OSError, ValueError, struct.error) as error:
                log.warning("Skipping the sleep screen: %s", error)
        log.info("Animations: %d, %d bytes", len(animations), sum(a.size for a in animations))
        self.device.set_animations(animations, sleep_animation, sleep["brightness"])

    def save_upload(self, name: str, data: bytes) -> str:
        """Stores an uploaded image, checking that it decodes before keeping it."""
        safe_name = layouts.safe_upload_name(name)
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with self._lock:
            folder = self.themes.uploads_dir()
            folder.mkdir(parents=True, exist_ok=True)
            (folder / safe_name).write_bytes(data)
        return f"art:uploads/{safe_name}"

    def set_brightness(self, level: int):
        self.brightness = max(0, min(100, level))
        self.device.set_brightness(self.brightness)

    def frame_png(self) -> Tuple[int, bytes]:
        """The picture's number and the picture. It's encoded once per change, not once per request."""
        with self._lock:
            frame_id, frame, cached = self._frame_id, self._frame, self._frame_png
        if cached[0] != frame_id:
            out = BytesIO()
            frame.save(out, "PNG")
            cached = (frame_id, out.getvalue())
            with self._lock:
                self._frame_png = cached
        return cached

    def status(self) -> dict:
        device = self.device.status
        stats = self.sensors.stats
        return {
            "version": VERSION,
            "connected": device.connected,
            "port": device.port,
            "bytesSent": device.bytes_sent,
            "updatesSent": device.updates_sent,
            "lastError": device.last_error,
            "firmware": self.firmware.state,
            "brightness": self.brightness,
            "layoutRevision": self.revision,
            "frame": self._frame_id,
            "cpu": stats.cpu_percent,
            "ram": stats.ram_percent,
        }

    def catalog(self) -> dict:
        """Everything the editor needs to build its forms."""
        return {"schema": layouts.SCHEMA, "files": layouts.list_files(), "tokens": layouts.TOKENS}

    def _tick_loop(self):
        while not self._stop.is_set():
            try:
                stats = self.sensors.stats if self._render_now.is_set() else self.sensors.update()
                self._render_now.clear()
                with self._lock:
                    current = self.layout
                stats.usb_connected = self.device.status.connected
                with layouts.ART_LOCK:
                    theme = self.themes.active
                    themed = themes.apply_layout(current, theme)
                    frame = themes.apply_tone(widgets.render(themed, stats, datetime.now()), themed, theme)
                pixels = codec.to_abgr1555(frame)
                with self._lock:
                    if self._frame_pixels is None or not np.array_equal(pixels, self._frame_pixels):
                        self._frame, self._frame_pixels = frame, pixels
                        self._frame_id += 1
                self.device.submit_frame(pixels)
            except Exception:
                log.exception("Render failed")
            with self._ticked:
                self._ticks += 1
                self._ticked.notify_all()

            # Wake just after the next second, or at once for a layout change.
            now = datetime.now()
            self._render_now.wait(1 - now.microsecond / 1_000_000 + 0.01)
