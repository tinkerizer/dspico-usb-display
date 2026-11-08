"""DS dashboard themes: colours applied over a layout, so they never move anything."""
import json
import re
from copy import deepcopy
from typing import Dict

import numpy as np
from PIL import Image

from . import layout as layouts
from . import templates

THEMES_PATH = layouts.LOCAL_DIR / "themes.json"
MAX_NAME = 24
NEUTRAL = 24    # Pixels whose channels differ by less than this count as grey.

BUILT_IN: Dict[str, dict] = {
    "Classic": {"paper": "#ffffff", "ink": "#000000", "boost": 0, "lift": 0, "bar": 11},
    "Dark": {"paper": "#1f2023", "ink": "#f4f4f6", "boost": 35, "lift": 35, "bar": 11},
}

# The DS profile colours, as in the menu's own table. Index matches art:topbar/N.png.
PROFILE_555 = (0xCE0C, 0x8137, 0x8C1F, 0xFE3F, 0x825F, 0x839E, 0x83F5, 0x83E0,
               0x9E80, 0xC769, 0xFAE6, 0xF960, 0xC800, 0xE811, 0xF41A, 0xC81F)


def profile_colour(index: int) -> str:
    value = PROFILE_555[index]
    return "#%02x%02x%02x" % tuple(((value >> shift) & 31) * 255 // 31 for shift in (0, 5, 10))


def _rgb(colour: str) -> np.ndarray:
    return np.array([int(colour[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float32)


def clean(theme: dict) -> dict:
    """Checks a theme from outside, keeping only what's expected. Raises ValueError."""
    out = {}
    for key in ("paper", "ink"):
        value = theme.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError(f"{key} must be a colour like #1f2023")
        out[key] = value.lower()
    for key, top in (("boost", 100), ("lift", 60), ("bar", 15)):
        value = theme.get(key, 0)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= top:
            raise ValueError(f"{key} must be a whole number from 0 to {top}")
        out[key] = value
    return out


def clean_name(name) -> str:
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"Theme names need 1 to {MAX_NAME} characters")
    return name


def apply_layout(layout: dict, theme: dict) -> dict:
    """The layout ready to draw: templates expanded, and the theme's profile colour in place of the default."""
    accent = profile_colour(theme["bar"])
    themed = deepcopy(templates.expand(layout, {"bar": theme["bar"]}))
    for element in themed["elements"]:
        props = element["props"]
        if str(props.get("file", "")).startswith("art:topbar/") and not element.get("from_template"):
            props["file"] = f"art:topbar/{theme['bar']}.png"
        for key, value in props.items():
            if key.endswith("_color") and value == layouts.PROFILE_COLOUR:
                props[key] = accent
    return themed


def apply_tone(frame: Image.Image, layout: dict, theme: dict) -> Image.Image:
    """Maps greys from ink to paper. The top bar is left alone, to keep its white text. Takes apply_layout's result."""
    if theme["paper"] == "#ffffff" and theme["ink"] == "#000000" and not theme["boost"] and not theme["lift"]:
        return frame
    pixels = np.asarray(frame.convert("RGB")).astype(np.float32)
    grey = (pixels.max(axis=2) - pixels.min(axis=2)) < NEUTRAL
    ink, paper = _rgb(theme["ink"]), _rgb(theme["paper"])
    level = pixels.mean(axis=2, keepdims=True) / 255
    black = theme["lift"] / 100     # Greys this dark or darker become full ink.
    level = np.clip((level - black) / (1 - black), 0, 1)
    out = np.where(grey[..., None], ink + (paper - ink) * level, pixels + (255 - pixels) * theme["boost"] / 100)
    for element in layout["elements"]:
        if str(element["props"].get("file", "")).startswith("art:topbar/") and not element["hidden"]:
            x, y, w, h = max(element["x"], 0), max(element["y"], 0), element["w"], element["h"]
            out[y:y + h, x:x + w] = pixels[y:y + h, x:x + w]
    return Image.fromarray(out.round().astype(np.uint8))


class ThemeStore:
    """The saved themes and which one is active. `preview` overrides it while editing."""

    def __init__(self, path=None):
        self.path = path or THEMES_PATH
        self.custom: Dict[str, dict] = {}
        self.active_name = "Classic"
        self.preview = None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.custom = {clean_name(name): clean(theme) for name, theme in saved.get("themes", {}).items()
                           if name not in BUILT_IN}
            if saved.get("active") in self.all():
                self.active_name = saved["active"]
        except (OSError, ValueError, AttributeError):
            pass

    def all(self) -> Dict[str, dict]:
        return {**BUILT_IN, **self.custom}

    @property
    def active(self) -> dict:
        return self.preview or self.all()[self.active_name]

    def listing(self) -> dict:
        return {"active": self.active_name, "themes": self.all(), "builtIn": list(BUILT_IN),
                "colours": [profile_colour(i) for i in range(16)]}

    def _write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"active": self.active_name, "themes": self.custom}, indent=2), encoding="utf-8")

    def use(self, name: str):
        if name not in self.all():
            raise ValueError("No theme with that name")
        self.active_name, self.preview = name, None
        self._write()

    def save(self, name, theme: dict):
        name = clean_name(name)
        if name in BUILT_IN:
            raise ValueError(f"{name} is built in, so save under a new name")
        self.custom[name] = clean(theme)
        self.use(name)

    def delete(self, name: str):
        if name not in self.custom:
            raise ValueError("Only saved themes can be deleted")
        del self.custom[name]
        if self.active_name == name:
            self.active_name = "Classic"
        self.preview = None
        self._write()
