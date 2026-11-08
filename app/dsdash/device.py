"""Owns the DS display port. One thread does all I/O, so nothing can interleave."""
import logging
import re
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from . import codec

log = logging.getLogger(__name__)

USB_VID, USB_PID = 0x1209, 0xDD01

MAGIC = 0xD5
PACKET_HELLO, PACKET_CLEAR, PACKET_BRIGHTNESS, PACKET_POWER = 1, 2, 3, 4
PACKET_RECT_RAW, PACKET_RECT_RLE = 5, 6
PACKET_KEEPALIVE = 9
KEEPALIVE_SECONDS = 1     # The DS goes dark after 5 s with no packets, so it notices a sleeping PC
PACKET_ANIM_BEGIN, PACKET_ANIM_FRAME, PACKET_ANIM_PLAY, PACKET_ANIM_RESET = 0x20, 0x21, 0x22, 0x24
PACKET_ANIM_SLEEP = 0x25
SLEEP_SLOT = 8      # The DS has 9 slots: 8 for the layout's GIFs, and this one for the sleep screen

ANIM_STORE_SIZE = 0x80000
SETTLE_SECONDS = 0.15   # The DS clears both screens just after the port opens


def packet(packet_type: int, payload: bytes = b"") -> bytes:
    return struct.pack("<BBHI", MAGIC, packet_type, 0, len(payload)) + payload + bytes(-len(payload) % 4)


def rect_packet(pixels: np.ndarray, x: int, y: int) -> bytes:
    """Encodes a rect, compressed when that is smaller."""
    header = struct.pack("<4H", x, y, pixels.shape[1], pixels.shape[0])
    encoded = codec.rle_encode(pixels.ravel())
    if len(encoded) < pixels.size * 2:
        return packet(PACKET_RECT_RLE, header + encoded)
    return packet(PACKET_RECT_RAW, header + pixels.astype("<u2").tobytes())


def find_display_port(ports) -> Optional[str]:
    """Interface 0 is display data; the other serial port is for dev tools."""
    for port in ports:
        if port.vid == USB_VID and port.pid == USB_PID:
            interface = re.search(r"\.(\d+)$", port.location or "")
            if not interface or int(interface.group(1)) == 0:
                return port.device
    return None


@dataclass
class Animation:
    rect: codec.Rect
    frames: List[Tuple[int, bytes]]

    @property
    def size(self) -> int:
        return sum(8 + ((len(body) + 3) & ~3) for _, body in self.frames)


@dataclass
class Status:
    connected: bool = False
    port: Optional[str] = None
    bytes_sent: int = 0
    updates_sent: int = 0
    last_error: str = ""


class DsDevice(threading.Thread):
    """
    Keeps the DS showing the newest submitted frame.

    Frames are latest-wins: if the link falls behind, it skips straight to the
    current picture instead of working through a backlog.
    """

    def __init__(self, open_port=None, list_ports=None):
        super().__init__(name="ds-device", daemon=True)
        self.status = Status()
        self._open_port = open_port or self._open_serial
        self._list_ports = list_ports or self._list_serial
        self._condition = threading.Condition()
        self._frame: Optional[np.ndarray] = None
        self._brightness = 100
        self._brightness_dirty = True
        self._animations: List[Animation] = []
        self._sleep: Tuple[Optional[Animation], int] = (None, 0)
        self._animations_dirty = True
        self._stopping = False
        self._screen = np.full((codec.HEIGHT, codec.WIDTH), codec.BLACK, dtype=np.uint16)

    # Called from other threads.

    def submit_frame(self, frame: np.ndarray):
        with self._condition:
            self._frame = frame
            self._condition.notify()

    def set_brightness(self, level: int):
        with self._condition:
            self._brightness = max(0, min(100, level))
            self._brightness_dirty = True
            self._condition.notify()

    def set_animations(self, animations: List[Animation], sleep: Optional[Animation] = None, sleep_brightness: int = 0):
        """The layout's GIFs, and the one the DS plays at sleep_brightness while the PC is asleep."""
        with self._condition:
            self._animations = animations
            self._sleep = (sleep, sleep_brightness)
            self._animations_dirty = True
            self._condition.notify()

    def stop(self):
        with self._condition:
            self._stopping = True
            self._condition.notify()

    # Device thread.

    @staticmethod
    def _list_serial():
        from serial.tools.list_ports import comports
        return comports()

    @staticmethod
    def _open_serial(device):
        import serial
        return serial.Serial(device, 115200, timeout=1, write_timeout=5, rtscts=False, dsrdtr=False)

    def run(self):
        while not self._stopping:
            device = find_display_port(self._list_ports())
            if not device:
                self.status.connected = False
                time.sleep(1)
                continue
            try:
                with self._open_port(device) as port:
                    self._session(port, device)
            except Exception as error:   # Serial errors vary by OS and driver
                self.status.last_error = str(error)
                log.warning("DS link lost: %s", error)
            self.status.connected = False
            self.status.port = None
            time.sleep(0.5)

    def _session(self, port, device: str):
        time.sleep(SETTLE_SECONDS)
        port.reset_input_buffer()
        port.write(packet(PACKET_HELLO))
        reply = port.readline()
        if not reply.startswith(b"ds_"):
            raise IOError(f"Unexpected HELLO reply {reply!r}")

        log.info("DS connected on %s: %s", device, reply.decode("ascii", "replace").strip())
        self._screen.fill(codec.BLACK)
        self.status.connected = True
        self.status.port = device
        with self._condition:
            self._brightness_dirty = True
            self._animations_dirty = True

        last_sent = time.monotonic()
        while True:
            with self._condition:
                while not (self._stopping or self._frame is not None or self._brightness_dirty
                           or self._animations_dirty):
                    if not self._condition.wait(timeout=1):
                        break
                if self._stopping:
                    return
                frame, self._frame = self._frame, None
                brightness = self._brightness if self._brightness_dirty else None
                self._brightness_dirty = False
                animations = (self._animations, self._sleep) if self._animations_dirty else None
                self._animations_dirty = False

            data = bytearray()
            if time.monotonic() - last_sent >= KEEPALIVE_SECONDS:
                data += packet(PACKET_KEEPALIVE)
            if brightness is not None:
                data += packet(PACKET_BRIGHTNESS, struct.pack("<I", brightness))
            if animations is not None:
                # The DS shows the live picture again where they were.
                data += packet(PACKET_ANIM_RESET)
            if frame is not None:
                data += self._frame_packets(frame)
            if animations is not None:
                data += self._animation_packets(*animations)
            if data:
                port.write(bytes(data))
                last_sent = time.monotonic()
                self.status.bytes_sent += len(data)
                self.status.updates_sent += 1

            # Nothing arriving is normal; this only notices a vanished port.
            if not port.is_open:
                raise IOError("Port closed")

    def _frame_packets(self, frame: np.ndarray) -> bytes:
        out = bytearray()
        for x, y, width, height in codec.changed_rects(self._screen, frame):
            pixels = np.ascontiguousarray(frame[y:y + height, x:x + width])
            out += rect_packet(pixels, x, y)
            self._screen[y:y + height, x:x + width] = pixels
        return bytes(out)

    def _animation_packets(self, animations: List[Animation], sleep=(None, 0)) -> bytes:
        out = bytearray()
        used = 0
        sleep_animation, sleep_brightness = sleep
        slots = list(enumerate(animations[:SLEEP_SLOT]))
        if sleep_animation:
            slots.append((SLEEP_SLOT, sleep_animation))
        for slot, animation in slots:
            used += animation.size
            if used > ANIM_STORE_SIZE:
                log.warning("Not enough DS memory for animation %d", slot)
                break
            out += packet(PACKET_ANIM_BEGIN, struct.pack("<II", slot, len(animation.frames)))
            for delay, body in animation.frames:
                out += packet(PACKET_ANIM_FRAME, struct.pack("<II", slot, delay) + body)
            if slot == SLEEP_SLOT:
                out += packet(PACKET_ANIM_SLEEP, struct.pack("<II", slot, sleep_brightness))
            else:
                out += packet(PACKET_ANIM_PLAY, struct.pack("<I", slot))
        return bytes(out)
