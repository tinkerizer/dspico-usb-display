"""Pixel formats and encodings for the DS display protocol (ds/common/DisplayProtocol.h)."""
import struct
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageSequence

WIDTH, HEIGHT = 256, 384
SCREEN_HEIGHT = 192
BLACK = 0x8000
VBLANK_MS = 16.715

MAX_RUN = 0x8000
MIN_RUN = 3   # Shorter runs cost less as literals

Rect = Tuple[int, int, int, int]  # x, y, width, height


TRANSPARENT = 0     # Bit 15 clear: in animations, the DS shows what's under the pixel


def to_abgr1555(image: Image.Image) -> np.ndarray:
    """Converts an image to a height x width array of opaque DS pixels."""
    rgb = np.asarray(image.convert("RGB"))
    r = rgb[..., 0].astype(np.uint16) >> 3
    g = rgb[..., 1].astype(np.uint16) >> 3
    b = rgb[..., 2].astype(np.uint16) >> 3
    return np.uint16(0x8000) | (b << 10) | (g << 5) | r


def rle_encode(pixels: np.ndarray) -> bytes:
    """Encodes a flat pixel array as RECT_RLE tokens."""
    if pixels.size == 0:
        return b""

    starts = np.flatnonzero(np.concatenate(([True], pixels[1:] != pixels[:-1])))
    lengths = np.diff(np.concatenate((starts, [pixels.size])))

    out = []
    literal_start = None

    def flush_literals(end):
        nonlocal literal_start
        position = literal_start
        while position is not None and position < end:
            count = min(end - position, MAX_RUN)
            out.append(struct.pack("<H", count - 1))
            out.append(pixels[position:position + count].astype("<u2").tobytes())
            position += count
        literal_start = None

    for start, length in zip(starts.tolist(), lengths.tolist()):
        if length < MIN_RUN:
            if literal_start is None:
                literal_start = start
            continue

        flush_literals(start)
        color = int(pixels[start])
        while length > 0:
            count = min(length, MAX_RUN)
            out.append(struct.pack("<HH", 0x8000 | (count - 1), color))
            length -= count

    flush_literals(pixels.size)
    return b"".join(out)


def _groups(indices: np.ndarray, gap: int) -> List[Tuple[int, int]]:
    """Splits sorted indices into (first, last + 1) runs, breaking at gaps wider than `gap`."""
    breaks = np.flatnonzero(np.diff(indices) > gap)
    firsts = np.concatenate(([0], breaks + 1))
    lasts = np.concatenate((breaks, [indices.size - 1]))
    return [(int(indices[a]), int(indices[b]) + 1) for a, b in zip(firsts, lasts)]


def changed_rects(previous: np.ndarray, current: np.ndarray, row_gap: int = 6, column_gap: int = 24) -> List[Rect]:
    """Finds rects covering every changed pixel, keeping separate changes separate."""
    changed = previous != current
    rows = np.flatnonzero(changed.any(axis=1))
    if rows.size == 0:
        return []

    rects = []
    for top, bottom in _groups(rows, row_gap):
        columns = np.flatnonzero(changed[top:bottom].any(axis=0))
        for left, right in _groups(columns, column_gap):
            band = np.flatnonzero(changed[top:bottom, left:right].any(axis=1))
            rects.append((left, top + int(band[0]), right - left, int(band[-1]) - int(band[0]) + 1))
    return rects


def rle_body(pixels: np.ndarray, x: int, y: int) -> bytes:
    return struct.pack("<4H", x, y, pixels.shape[1], pixels.shape[0]) + rle_encode(pixels.ravel())


def encode_animation(path: str, rect: Rect, crop: Optional[Rect] = None) -> Tuple[Rect, List[Tuple[int, bytes]]]:
    """
    Returns the area it covers and (delay in VBlanks, RLE body) per frame for the DS animation
    player. Transparent pixels have bit 15 clear, and the DS shows the live picture through them.
    The area is trimmed to what the frames use.

    `crop` selects part of the source, as x, y, width, height. It is then scaled to fit.

    The first frame is the whole picture and the rest are changes from the frame
    before. The last returns to the first, so playback loops by repeating
    everything after the first frame.
    """
    x, y, width, height = rect
    pictures, delays, used = [], [], None
    with Image.open(path) as gif:
        for frame in ImageSequence.Iterator(gif):
            delays.append(max(1, round(frame.info.get("duration", 100) / VBLANK_MS)))
            rgba = frame.convert("RGBA")
            if crop:
                rgba = rgba.crop((crop[0], crop[1], crop[0] + crop[2], crop[1] + crop[3]))
            rgba = rgba.resize((width, height), Image.NEAREST)
            box = rgba.getchannel("A").getbbox()
            if box:
                used = box if not used else (min(used[0], box[0]), min(used[1], box[1]),
                                             max(used[2], box[2]), max(used[3], box[3]))
            # GIF pixels are fully opaque or fully transparent.
            pictures.append(np.where(np.asarray(rgba.getchannel("A")) >= 128, to_abgr1555(rgba), TRANSPARENT).astype(np.uint16))

    # Elements can hang off the screen, so keep only the part the DS can show.
    if not used:
        raise ValueError("Animation is fully transparent")
    left, top = max(used[0], -x), max(used[1], -y)
    right, bottom = min(used[2], WIDTH - x), min(used[3], HEIGHT - y)
    if right <= left or bottom <= top:
        raise ValueError("Animation is off the screen")
    pictures = [np.ascontiguousarray(picture[top:bottom, left:right]) for picture in pictures]
    x, y = x + left, y + top

    def delta(old, new):
        moved = old != new
        if not moved.any():
            return struct.pack("<4H", x, y, 0, 0)
        rows = np.flatnonzero(moved.any(axis=1))
        columns = np.flatnonzero(moved.any(axis=0))
        top, bottom = int(rows[0]), int(rows[-1]) + 1
        left, right = int(columns[0]), int(columns[-1]) + 1
        return rle_body(np.ascontiguousarray(new[top:bottom, left:right]), x + left, y + top)

    frames = [(delays[0], rle_body(pictures[0], x, y))]
    for index in range(1, len(pictures)):
        frames.append((delays[index], delta(pictures[index - 1], pictures[index])))
    if len(pictures) > 1:
        frames.append((delays[0], delta(pictures[-1], pictures[0])))
    return (x, y, right - left, bottom - top), frames


def drawing_box(path: str) -> Rect:
    """The part of a GIF that's drawn on, over every frame: not transparent, and not the corner's colour."""
    box = None
    with Image.open(path) as gif:
        background = None
        for frame in ImageSequence.Iterator(gif):
            pixels = np.asarray(frame.convert("RGBA")).astype(np.int16)
            if background is None:
                background = pixels[0, 0]
            drawn = (pixels[..., 3] >= 128) & (np.abs(pixels[..., :3] - background[:3]).max(axis=2) > 8)
            rows, columns = np.flatnonzero(drawn.any(axis=1)), np.flatnonzero(drawn.any(axis=0))
            if len(rows):
                found = (int(columns[0]), int(rows[0]), int(columns[-1]) + 1, int(rows[-1]) + 1)
                box = found if box is None else (min(box[0], found[0]), min(box[1], found[1]),
                                                 max(box[2], found[2]), max(box[3], found[3]))
    if box is None:
        raise ValueError("Nothing is drawn in that GIF")
    return box[0], box[1], box[2] - box[0], box[3] - box[1]


def encode_sleep(path: str, screen: str) -> Tuple[Rect, List[Tuple[int, bytes]]]:
    """A GIF for the sleep screen: cropped to its drawing, shrunk to fit if needed, and centred on a screen."""
    crop = drawing_box(path)
    scale = min(1, WIDTH / crop[2], SCREEN_HEIGHT / crop[3])
    width, height = max(1, int(crop[2] * scale)), max(1, int(crop[3] * scale))
    top = SCREEN_HEIGHT if screen == "bottom" else 0
    rect = ((WIDTH - width) // 2, top + (SCREEN_HEIGHT - height) // 2, width, height)
    return encode_animation(path, rect, crop)
