"""DS dashboard themes. Each is a folder: theme.json, with its colours and layout, and all of its art. See docs/THEMES.md."""
import hashlib
import json
import logging
import os
import re
import shutil
import zipfile
from copy import deepcopy
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Dict

import numpy as np
from PIL import Image

from . import layout as layouts
from . import templates

log = logging.getLogger(__name__)

MAX_NAME = 24
NEUTRAL = 24    # Pixels whose channels differ by less than this count as grey.
DEFAULT = "Classic"
SLEEP_DEFAULT = {"file": "", "screen": "top", "brightness": 30}
MAX_ZIP_FILES, MAX_ZIP_BYTES = 500, 64 * 1024 * 1024
# Built-in art that has been corrected since. A theme's copy is replaced if it's still the old file.
OLD_ART = {"quickmenu/topbg.png": "67403e6f89136544ac02b08f3ca9e4e94e1ca559"}

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
            found[clean_name(read_file(folder).get("name"))] = folder
        except (OSError, ValueError, AttributeError) as error:
            log.warning("Theme %s skipped: %s", folder.name, error)
    return found


def read_file(folder: Path) -> dict:
    return json.loads((folder / "theme.json").read_text(encoding="utf-8"))


def read(folder: Path) -> dict:
    """A theme's colours."""
    return clean(read_file(folder))


def read_layout(folder: Path) -> dict:
    return layouts.from_saved(read_file(folder).get("layout"))


def write(folder: Path, **changes):
    """Changes some of a theme's fields, keeping the rest. Writes through a temporary file, so a crash
    can't leave half a theme."""
    folder.mkdir(parents=True, exist_ok=True)
    try:
        info = read_file(folder)
    except (OSError, ValueError):
        info = {}
    info.update(changes)
    temporary = folder / "theme.json.tmp"
    temporary.write_text(json.dumps(info, indent=2), encoding="utf-8")
    os.replace(temporary, folder / "theme.json")


def clean_sleep(sleep) -> dict:
    """The sleep screen: a GIF from the theme's folder, or "" for black, its screen and its brightness."""
    sleep = sleep if isinstance(sleep, dict) else {}
    out = {**SLEEP_DEFAULT, **{key: sleep[key] for key in SLEEP_DEFAULT if key in sleep}}
    if out["file"] and (not isinstance(out["file"], str) or not out["file"].lower().endswith(".gif")):
        raise ValueError("The sleep screen needs a GIF")
    if out["file"]:
        layouts.resolve_file(out["file"])
    if out["screen"] not in ("top", "bottom"):
        raise ValueError("The sleep screen is top or bottom")
    brightness = out["brightness"]
    if not isinstance(brightness, int) or isinstance(brightness, bool) or not 0 <= brightness <= 100:
        raise ValueError("Sleep brightness must be a whole number from 0 to 100")
    return out


def folder_name(name: str, taken) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "theme"
    candidate, number = stem, 2
    while candidate in taken:
        candidate, number = f"{stem}_{number}", number + 1
    return candidate


class ThemeStore:
    """The themes, which one is active, and its folder. `preview` overrides its colours while editing.

    Built-in themes are in assets/themes and the user's in the data folder's themes, each a whole
    folder. Changing a built-in one writes a copy to the data folder, which then replaces it, and
    deleting that copy brings the original back. Saving under a new name copies the whole theme.
    """

    def __init__(self, data_dir=None, built_in_dir=None):
        data_dir = data_dir or layouts.LOCAL_DIR
        self.state_path = data_dir / "themes.json"
        self.user_dir = data_dir / "themes"
        self.built_in = load_folders(built_in_dir or layouts.THEMES_DIR)
        self.preview = None
        state = {}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        self._convert_old(state.get("themes"))
        self._load_user()
        self.active_name = state.get("active") if state.get("active") in self.folders() else DEFAULT
        self._point_art()
        self._move_old_layout(data_dir)
        if "themes" in state:
            self._write_state()

    def _load_user(self):
        user = load_folders(self.user_dir)
        self.custom = {name: folder for name, folder in user.items() if name not in self.built_in}
        self.edited = {name: folder for name, folder in user.items() if name in self.built_in}
        for folder in user.values():
            self._add_sleep_screen(folder)
            self._refresh_art(folder)

    def _refresh_art(self, folder: Path):
        source = self.built_in.get(DEFAULT)
        for name, old in OLD_ART.items():
            file = folder / name
            if source and file.is_file() and hashlib.sha1(file.read_bytes()).hexdigest() == old:
                shutil.copy2(source / name, file)

    def _add_sleep_screen(self, folder: Path):
        """Themes made before sleep screens get Classic's."""
        source = self.built_in.get(DEFAULT)
        if source is None or "sleep" in read_file(folder):
            return
        if (source / "sleep").is_dir() and not (folder / "sleep").exists():
            shutil.copytree(source / "sleep", folder / "sleep")
        write(folder, sleep=read_file(source).get("sleep", SLEEP_DEFAULT))

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
            source = self.built_in[DEFAULT]
            folder = self.user_dir / folder_name(name, self._taken())
            shutil.copytree(source, folder, ignore=shutil.ignore_patterns("theme.json"))
            write(folder, name=name, **theme, layout=read_file(source).get("layout"))

    def _move_old_layout(self, data_dir: Path):
        """The layout and uploads used to be shared by every theme. They go to the active theme and the user's own."""
        old = data_dir / "layout.json"
        if not old.exists():
            return
        try:
            layout = layouts.from_saved(json.loads(old.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return
        uploads = [path for path in data_dir.iterdir() if path.is_file() and path.suffix.lower() in layouts.IMAGE_SUFFIXES]
        folders = set(self.custom.values()) | {self._writable(self.active_name)}
        for folder in folders:
            (folder / "uploads").mkdir(parents=True, exist_ok=True)
            for path in uploads:
                shutil.copy2(path, folder / "uploads" / path.name)
            info = read_file(folder)
            write(folder, layout=layout)
        os.replace(old, old.with_name("layout.json.old"))

    def _taken(self):
        return {path.name for path in self.user_dir.iterdir()} if self.user_dir.is_dir() else set()

    def _writable(self, name: str) -> Path:
        """The folder to change for a theme, copying a built-in one first."""
        folders = self.folders()
        if name in self.built_in and name not in self.edited:
            folder = self.user_dir / self.built_in[name].name
            shutil.copytree(self.built_in[name], folder, dirs_exist_ok=True)
            self.edited[name] = folder
            if name == self.active_name:
                self._point_art()
            return folder
        return folders[name]

    def folders(self) -> Dict[str, Path]:
        return {**self.built_in, **self.edited, **self.custom}

    def all(self) -> Dict[str, dict]:
        return {name: read(folder) for name, folder in self.folders().items()}

    @property
    def folder(self) -> Path:
        return self.folders()[self.active_name]

    @property
    def active(self) -> dict:
        return self.preview or read(self.folder)

    @property
    def layout(self) -> dict:
        return read_layout(self.folder)

    def save_layout(self, layout: dict):
        folder = self._writable(self.active_name)
        write(folder, layout=layout)

    @property
    def sleep(self) -> dict:
        try:
            return clean_sleep(read_file(self.folder).get("sleep"))
        except ValueError:
            return dict(SLEEP_DEFAULT)

    def set_sleep(self, sleep: dict):
        write(self._writable(self.active_name), sleep=clean_sleep(sleep))

    def uploads_dir(self) -> Path:
        return self._writable(self.active_name) / "uploads"

    def listing(self) -> dict:
        stamps = {name: (folder / "theme.json").stat().st_mtime_ns for name, folder in self.folders().items()}
        return {"active": self.active_name, "themes": self.all(), "builtIn": list(self.built_in), "stamps": stamps,
                "edited": list(self.edited), "colours": [profile_colour(i) for i in range(16)],
                "sleep": self.sleep, "gifs": [file for file in layouts.list_files() if file.endswith(".gif")]}

    def _point_art(self):
        with layouts.ART_LOCK:
            layouts.ART_DIR = self.folder

    def export(self, name: str) -> bytes:
        """A theme's folder as a zip, to share."""
        folder = self.folders().get(name)
        if folder is None:
            raise ValueError("No theme with that name")
        out = BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file() and (path.name == "theme.json" or path.suffix.lower() in layouts.IMAGE_SUFFIXES):
                    archive.write(path, path.relative_to(folder).as_posix())
        return out.getvalue()

    def import_zip(self, data: bytes) -> str:
        """Adds a theme from a zip made by export, and switches to it. Only its theme.json and images are
        taken, and nothing can land outside its folder. A name that's taken gets a number."""
        try:
            archive = zipfile.ZipFile(BytesIO(data))
        except zipfile.BadZipFile:
            raise ValueError("That isn't a theme zip")
        with archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
            if len(members) > MAX_ZIP_FILES or sum(member.file_size for member in members) > MAX_ZIP_BYTES:
                raise ValueError("That zip is too big for a theme")
            # theme.json is at the top, or in one folder if the theme's folder was zipped.
            tops = sorted((PurePosixPath(m.filename) for m in members if PurePosixPath(m.filename).name == "theme.json"),
                          key=lambda path: len(path.parts))
            if not tops:
                raise ValueError("That zip has no theme.json")
            root = tops[0].parent
            try:
                info = json.loads(archive.read(str(tops[0])))
                wanted, colours = clean_name(info.get("name")), clean(info)
            except (ValueError, AttributeError, KeyError) as error:
                raise ValueError(f"That theme can't be read: {error}")
            name, number = wanted, 2
            while name in self.folders():
                suffix = f" {number}"
                name, number = wanted[:MAX_NAME - len(suffix)] + suffix, number + 1
            folder = self.user_dir / folder_name(name, self._taken())
            for member in members:
                path = PurePosixPath(member.filename.replace("\\", "/"))
                if root not in path.parents and root != PurePosixPath("."):
                    continue
                inside = path.relative_to(root)
                plain = all(re.fullmatch(r"[A-Za-z0-9_ .()-]+", part) and part.strip(". ") for part in inside.parts)
                if not plain or inside.suffix.lower() not in layouts.IMAGE_SUFFIXES:
                    continue
                target = folder / inside
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
            write(folder, **colours, name=name, sleep=info.get("sleep"), layout=info.get("layout"))
        self.custom[name] = folder
        self.use(name)
        return name

    def _write_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps({"active": self.active_name}, indent=2), encoding="utf-8")

    def use(self, name: str):
        if name not in self.folders():
            raise ValueError("No theme with that name")
        self.active_name, self.preview = name, None
        self._point_art()
        self._write_state()

    def set_colours(self, theme: dict):
        """Changes the active theme's colours, keeping the rest of it."""
        write(self._writable(self.active_name), **clean(theme))
        self.preview = None

    def save(self, name, theme: dict):
        """Saves the colours under a name. A new name copies the active theme: its art, uploads and layout."""
        name, theme = clean_name(name), clean(theme)
        if name in self.folders():
            folder = self._writable(name)
        else:
            folder = self.user_dir / folder_name(name, self._taken())
            shutil.copytree(self.folder, folder)
            self.custom[name] = folder
        write(folder, name=name, **theme)
        self.use(name)

    def delete(self, name: str):
        """Deletes a theme of the user's own, or puts a changed built-in one back as it was."""
        if name in self.custom:
            shutil.rmtree(self.custom.pop(name), ignore_errors=True)
            if self.active_name == name:
                self.active_name = DEFAULT
        elif name in self.edited:
            shutil.rmtree(self.edited.pop(name), ignore_errors=True)
        else:
            raise ValueError("Built-in themes can't be deleted")
        self.preview = None
        self._point_art()
        self._write_state()


BUILT_IN: Dict[str, dict] = {name: read(folder) for name, folder in load_folders(layouts.THEMES_DIR).items()}
