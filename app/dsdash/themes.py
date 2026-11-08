"""DS dashboard themes. Each is a folder with theme.json, its colours, and all of its art. See docs/THEMES.md."""
import json
import logging
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Dict

import numpy as np
from PIL import Image

from . import layout as layouts
from . import templates

log = logging.getLogger(__name__)

STATE_PATH = layouts.LOCAL_DIR / "themes.json"     # Which theme is active
USER_DIR = layouts.LOCAL_DIR / "themes"
MAX_NAME = 24
NEUTRAL = 24    # Pixels whose channels differ by less than this count as grey.
DEFAULT = "Classic"

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


def load_folders(parent: Path) -> Dict[str, Path]:
    """Every theme folder in parent, by its name. A broken one is logged and skipped."""
    found = {}
    for folder in sorted(parent.iterdir()) if parent.is_dir() else []:
        try:
            info = json.loads((folder / "theme.json").read_text(encoding="utf-8"))
            found[clean_name(info.get("name"))] = folder
        except (OSError, ValueError, AttributeError) as error:
            log.warning("Theme %s skipped: %s", folder.name, error)
    return found


def read(folder: Path) -> dict:
    return clean(json.loads((folder / "theme.json").read_text(encoding="utf-8")))


def write(folder: Path, name: str, theme: dict):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "theme.json").write_text(json.dumps({"name": name, **clean(theme)}, indent=2), encoding="utf-8")


def folder_name(name: str, taken) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "theme"
    candidate, number = stem, 2
    while candidate in taken:
        candidate, number = f"{stem}_{number}", number + 1
    return candidate


class ThemeStore:
    """The themes, which one is active, and its art folder. `preview` overrides its colours while editing.

    Built-in themes are in assets/themes and saved ones in the data folder's themes, each a whole
    folder. Saving copies the active theme's art, so every theme has all of its own.
    """

    def __init__(self, state_path=None, user_dir=None, built_in_dir=None):
        self.state_path = state_path or STATE_PATH
        self.user_dir = user_dir or USER_DIR
        self.built_in = load_folders(built_in_dir or layouts.THEMES_DIR)
        self.preview = None
        state = {}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self._convert_old(state.get("themes"))
        self.custom = {name: folder for name, folder in load_folders(self.user_dir).items() if name not in self.built_in}
        self.active_name = state.get("active") if state.get("active") in self.folders() else DEFAULT
        self._point_art()
        if "themes" in state:
            self._write_state()

    def _convert_old(self, saved):
        """Saved themes used to be colours only, in themes.json. Each becomes a folder with Classic's art."""
        if not isinstance(saved, dict):
            return
        for name, theme in saved.items():
            try:
                name, theme = clean_name(name), clean(theme)
            except ValueError:
                continue
            if name in self.built_in or name in load_folders(self.user_dir):
                continue
            folder = self.user_dir / folder_name(name, self._taken())
            shutil.copytree(self.built_in[DEFAULT], folder, ignore=shutil.ignore_patterns("theme.json"))
            write(folder, name, theme)

    def _taken(self):
        return {path.name for path in self.user_dir.iterdir()} if self.user_dir.is_dir() else set()

    def folders(self) -> Dict[str, Path]:
        return {**self.built_in, **self.custom}

    def all(self) -> Dict[str, dict]:
        return {name: read(folder) for name, folder in self.folders().items()}

    @property
    def folder(self) -> Path:
        return self.folders()[self.active_name]

    @property
    def active(self) -> dict:
        return self.preview or read(self.folder)

    def listing(self) -> dict:
        return {"active": self.active_name, "themes": self.all(), "builtIn": list(self.built_in),
                "colours": [profile_colour(i) for i in range(16)]}

    def _point_art(self):
        layouts.ART_DIR = self.folder

    def _write_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"active": self.active_name}, indent=2), encoding="utf-8")

    def use(self, name: str):
        if name not in self.folders():
            raise ValueError("No theme with that name")
        self.active_name, self.preview = name, None
        self._point_art()
        self._write_state()

    def save(self, name, theme: dict):
        """Saves the colours under a name. A new theme starts with a copy of the active theme's art."""
        name, theme = clean_name(name), clean(theme)
        if name in self.built_in:
            raise ValueError(f"{name} is built in, so save under a new name")
        folder = self.custom.get(name)
        if folder is None:
            folder = self.user_dir / folder_name(name, self._taken())
            shutil.copytree(self.folder, folder, ignore=shutil.ignore_patterns("theme.json"))
            self.custom[name] = folder
        write(folder, name, theme)
        self.use(name)

    def delete(self, name: str):
        if name not in self.custom:
            raise ValueError("Only saved themes can be deleted")
        shutil.rmtree(self.custom.pop(name), ignore_errors=True)
        if self.active_name == name:
            self.active_name = DEFAULT
        self.preview = None
        self._point_art()
        self._write_state()


BUILT_IN: Dict[str, dict] = {name: read(folder) for name, folder in load_folders(layouts.THEMES_DIR).items()}
