"""Ties the pieces together: read sensors, render, hand frames to the device."""
import logging
import struct
import threading
import time
from datetime import datetime
from io import BytesIO
from typing import List, Optional, Tuple

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
        self.layout = layouts.load()
        # Starts from the clock so it keeps rising when the app restarts, which
        # stops a tab left open from matching a revision it never saw.
        self.revision = time.time_ns() // 1_000_000
        self.brightness = 100
        self._frame = Image.new("RGB", (256, 384))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._render_now = threading.Event()
        self._animation_key = None

    def start(self):
        self.device.start()
        self.firmware.start()
        self._load_animations()
        threading.Thread(target=self._tick_loop, name="ds-render", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._render_now.set()
        self.device.stop()
        self.firmware.stop()

    def set_layout(self, new_layout: dict, revision: Optional[int] = None) -> Tuple[dict, int]:
        """Saves unless revision is given and out of date. Returns the layout and its revision."""
        clean = layouts.validate(new_layout)
        with self._lock:
            if revision is not None and revision != self.revision:
                raise LayoutConflict("Another tab changed the layout")
            layouts.save(clean)
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
            else:
                raise ValueError("Unknown theme action")
            self._load_animations()
        self._render_now.set()
        return self.themes.listing()

    def reset_layout(self, revision: Optional[int] = None) -> Tuple[dict, int]:
        return self.set_layout(layouts.default_layout(), revision)

    def _load_animations(self):
        """Re-encodes only when something that affects the animations changed."""
        theme = self.themes.active
        themed = themes.apply_layout(self.layout, theme)
        elements = [e for e in themed["elements"] if e["type"] == "animation" and not e["hidden"]]
        key = repr(elements)
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
        log.info("Animations: %d, %d bytes", len(animations), sum(a.size for a in animations))
        self.device.set_animations(animations)

    def save_upload(self, name: str, data: bytes) -> str:
        """Stores an uploaded image, checking that it decodes before keeping it."""
        safe_name = layouts.safe_upload_name(name)
        with Image.open(BytesIO(data)) as image:
            image.verify()
        layouts.LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        (layouts.LOCAL_DIR / safe_name).write_bytes(data)
        return f"local:{safe_name}"

    def set_brightness(self, level: int):
        self.brightness = max(0, min(100, level))
        self.device.set_brightness(self.brightness)

    def frame_png(self) -> bytes:
        with self._lock:
            frame = self._frame
        out = BytesIO()
        frame.save(out, "PNG")
        return out.getvalue()

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
                theme = self.themes.active
                themed = themes.apply_layout(current, theme)
                frame = themes.apply_tone(widgets.render(themed, stats, datetime.now()), themed, theme)
                with self._lock:
                    self._frame = frame
                self.device.submit_frame(codec.to_abgr1555(frame))
            except Exception:
                log.exception("Render failed")

            # Wake just after the next second, or at once for a layout change.
            now = datetime.now()
            self._render_now.wait(1 - now.microsecond / 1_000_000 + 0.01)
