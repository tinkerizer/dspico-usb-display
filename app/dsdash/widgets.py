"""Draws layouts, and what the element types in elements/ share: fonts, art and tokens."""
import math
import platform
import re
from datetime import datetime
from pathlib import Path
from functools import lru_cache

import numpy as np
from PIL import Image, ImageFont, ImageSequence

from . import layout as layouts
from .sensors import Stats

# The menu button frame in grf/box.bmp: raised on top, flat below. The web editor uses it for its buttons.
BUTTON_FRAMES = {"raised": (7, 4, 57, 54), "flat": (7, 68, 57, 118)}


@lru_cache(maxsize=8)
def font(size: int):
    return ImageFont.truetype(str(layouts.ASSETS / "fonts" / "fusion-pixel-10px-monospaced-zh_hans.otf"), size)


def _remove_key_color(image: Image.Image) -> Image.Image:
    """Sprites use magenta for transparency."""
    image = image.convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, _ = pixels[x, y]
            if r > 240 and g < 16 and b > 240:
                pixels[x, y] = (0, 0, 0, 0)
    return image


def load_art(reference: str) -> Image.Image:
    return _load_image(str(layouts.resolve_file(reference)))


@lru_cache(maxsize=64)
def _load_image(name: str) -> Image.Image:
    path = Path(name)
    with Image.open(path) as image:
        if path.suffix.lower() == ".gif":
            image = next(ImageSequence.Iterator(image)).copy()
        return _remove_key_color(image)


def button_frame(style: str) -> Image.Image:
    """The button art with its transparent margin removed, for CSS border images."""
    return load_art("art:grf/box.bmp").crop(BUTTON_FRAMES[style])


def menu_art() -> Image.Image:
    """The top menu art, with the sprite over the clock's corner cleaned up."""
    return _menu_art(str(layouts.ART_DIR))


@lru_cache(maxsize=4)
def _menu_art(folder: str) -> Image.Image:
    with Image.open(Path(folder) / "background" / "top.png") as image:
        top = image.convert("RGB")
    corner = top.crop((15, 30, 32, 42)).transpose(Image.FLIP_LEFT_RIGHT)
    top.paste(corner, (95, 30))
    return top


def pixel_scale(path) -> int:
    """Finds how much pixel art was scaled up, by the largest block size that fits it."""
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("RGB"))
    height, width = pixels.shape[:2]
    for scale in range(min(math.gcd(width, height), 32), 1, -1):
        if width % scale or height % scale:
            continue
        blocks = pixels.reshape(height // scale, scale, width // scale, scale, 3)
        if (blocks == blocks[:, :1, :, :1]).all():
            return scale
    return 1


def format_rate(value: float) -> str:
    for unit in ("B/s", "K/s", "M/s"):
        if value < 1024:
            return f"{value:.0f}{unit}"
        value /= 1024
    return f"{value:.0f}G/s"


def token_values(stats: Stats, now: datetime) -> dict:
    return {
        "host": platform.node(),
        "time": now.strftime("%H:%M"),
        "seconds": now.strftime("%S"),
        "date": now.strftime("%d %b"),
        "weekday": now.strftime("%A"),
        "month": now.strftime("%B"),
        "year": now.strftime("%Y"),
        "cpu": f"{stats.cpu_percent:.0f}%",
        "ram": f"{stats.ram_percent:.0f}%",
        "ram_used": f"{stats.ram_used_gb:.1f}G",
        "ram_total": f"{stats.ram_total_gb:.0f}G",
        "disk": f"{stats.disk_percent:.0f}%",
        "disk_free": f"{stats.disk_free_gb:.0f}G",
        "net_up": format_rate(stats.net_up),
        "net_down": format_rate(stats.net_down),
        "gpu": "--" if stats.gpu_percent is None else f"{stats.gpu_percent:.0f}%",
        "gpu_memory": "--" if stats.gpu_memory_gb is None else f"{stats.gpu_memory_gb:.1f}G",
        "temp": "--" if stats.temperature is None else f"{stats.temperature:.0f}°",
    }


def expand_tokens(text: str, values: dict) -> str:
    """Replaces known {tokens} and leaves everything else as typed."""
    return re.sub(r"\{(\w+)\}", lambda match: values.get(match.group(1), match.group(0)), text)


def render(layout: dict, stats: Stats, now: datetime) -> Image.Image:
    """Draws the layout in order. A broken element is skipped, not fatal."""
    from . import elements
    canvas = Image.new("RGB", (256, 384), "#000000")
    for element in layout["elements"]:
        draw = elements.DRAW.get(element["type"])
        if draw is None or element["hidden"]:
            continue
        try:
            draw(canvas, element, stats, now)
        except (OSError, ValueError, KeyError):
            pass
    return canvas

