"""Dashboards as data: a list of elements, the schema that describes them, and validation."""
import os
import re
import sys
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Dict, List

from . import elements

# A packaged build unpacks read-only assets to a temporary folder, so anything
# the user creates has to live somewhere that lasts.
FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
THEMES_DIR = ASSETS / "themes"
ART_DIR = THEMES_DIR / "classic"    # The active theme's folder, which art: paths are in. themes.ThemeStore sets it.
APP_DATA = Path(os.environ.get("LOCALAPPDATA", ".")) / "DSDisplay"
LOCAL_DIR = APP_DATA / "data" if FROZEN else ASSETS / "local"
ART_LOCK = threading.RLock()        # Held while drawing, and while ART_DIR changes


@contextmanager
def art_folder(folder: Path):
    """Draws from another theme's folder for a moment, as its thumbnail needs."""
    global ART_DIR
    with ART_LOCK:
        previous, ART_DIR = ART_DIR, folder
        try:
            yield
        finally:
            ART_DIR = previous

WIDTH, HEIGHT = 256, 384
PROFILE_COLOUR = "#005af6"  # Blue, matching topbar/11.png.
MAX_ELEMENTS = 100
MAX_ANIMATIONS = 8
MAX_TEXT = 200
VERSION = 2

IMAGE_SUFFIXES = (".png", ".bmp", ".gif")

TOKENS = ["host", "time", "seconds", "date", "weekday", "month", "year", "cpu", "ram", "ram_used", "ram_total",
          "disk", "disk_free", "net_up", "net_down", "gpu", "gpu_memory", "temp"]

# Element types: the built-in ones from elements/, then templates, added when they load.
SCHEMA: Dict[str, dict] = dict(elements.SCHEMA)


def _element(id_: str, type_: str, x: int, y: int, w: int, h: int, **props) -> dict:
    values = {prop["key"]: prop["default"] for prop in SCHEMA[type_]["props"]}
    values.update(props)
    locked = values.pop("locked", False)
    return {"id": id_, "type": type_, "x": x, "y": y, "w": w, "h": h, "hidden": False, "locked": locked,
            "props": values}


def gpu_panel_elements() -> list:
    """The top box: load, temperature and network, with a graph of the GPU beside them."""
    return [
        _element("card_gpu", "text", 83, 222, 62, 12, text="GPU  {gpu}"),
        _element("card_temp", "temperature", 83, 234, 62, 12, text="TEMP "),
        _element("card_net", "text", 83, 246, 62, 12, text="NET  {net_down}", color="#0041c3"),
        _element("gpu_graph", "graph", 147, 222, 70, 35, metric="gpu", color="#b3202a"),
    ]


def corner_icon_elements() -> list:
    """The small icons along the bottom of the real menu."""
    return [
        _element("corner_brightness", "image", 10, 367, 16, 16, file="art:grf/cornericons.png",
                 crop_x=0, crop_y=0, crop_w=16, crop_h=16, locked=True),
        _element("corner_settings", "image", 117, 362, 32, 22, file="art:grf/menu_settings.png",
                 crop_x=0, crop_y=0, crop_w=32, crop_h=22, locked=True),
        _element("corner_manual", "image", 235, 367, 16, 16, file="art:grf/cornericons.png",
                 crop_x=0, crop_y=96, crop_w=16, crop_h=16, locked=True),
    ]


def default_layout() -> dict:
    """The DS home screen, laid out like the real menu and built from its art."""
    ink = "#424242"
    return {"version": VERSION, "elements": [
        # Top screen: clock, calendar and the date, as on the real menu.
        _element("top_paper", "image", 0, 0, 256, 192, file="art:quickmenu/topbg.png", locked=True),
        _element("top_bar", "top_bar", 0, 0, 256, 16),
        _element("clock", "clock", 15, 31, 97, 97, second_color=PROFILE_COLOUR),
        _element("calendar", "calendar", 127, 31, 113, 97, today_color=PROFILE_COLOUR),
        _element("weekday", "text", 88, 18, 80, 12, text="{weekday}", align="center"),
        _element("digital_time", "text", 23, 146, 80, 24, text="{time}", size="20", align="center"),
        _element("month", "text", 133, 152, 100, 12, text="{month} {year}", align="center"),

        # Bottom screen: the real menu's boxes, in its positions.
        _element("bottom_paper", "image", 0, 192, 256, 192, file="art:quickmenu/bottombg.png", locked=True),
        *corner_icon_elements(),

        _element("card", "button", 33, 217, 189, 45),
        _element("cloud", "animation", 36, 221, 40, 36),
        *gpu_panel_elements(),

        _element("cpu_button", "button", 33, 265, 93, 45),
        _element("cpu_label", "text", 39, 267, 40, 12, text="CPU"),
        _element("cpu_value", "text", 78, 267, 44, 12, text="{cpu}", align="right", color="#0041c3"),
        _element("cpu_graph", "graph", 38, 281, 83, 24, metric="cpu", color="#0041c3"),

        _element("ram_button", "button", 129, 265, 93, 45),
        _element("ram_label", "text", 135, 267, 40, 12, text="RAM"),
        _element("ram_value", "text", 174, 267, 44, 12, text="{ram}", align="right", color="#28aa3c"),
        _element("ram_graph", "graph", 134, 281, 83, 24, metric="ram", color="#28aa3c"),

        _element("disk_button", "button", 33, 313, 189, 45),
        _element("disk_label", "text", 39, 315, 40, 12, text="DISK", color=ink),
        _element("disk_bar", "bar", 41, 336, 173, 10, metric="disk", color="#d30000"),
        _element("disk_value", "text", 178, 315, 40, 12, text="{disk_free}", align="right"),
    ]}


class LayoutError(ValueError):
    pass


def resolve_file(reference: str) -> Path:
    """Maps art:path to a file in the active theme's folder, refusing anything outside it."""
    prefix, _, name = reference.partition(":")
    base = ART_DIR
    if prefix != "art" or not name:
        raise LayoutError(f"Bad file reference {reference!r}")

    path = (base / name).resolve()
    if base.resolve() not in path.parents or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise LayoutError(f"Bad file reference {reference!r}")
    return path


def list_files() -> List[str]:
    return [f"art:{path.relative_to(ART_DIR).as_posix()}" for path in sorted(ART_DIR.rglob("*"))
            if path.suffix.lower() in IMAGE_SUFFIXES]


def safe_upload_name(name: str) -> str:
    """Keeps a plain file name, so uploads can only land directly in the local folder."""
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(name).name).lstrip(".")
    if not stem or Path(stem).suffix.lower() not in IMAGE_SUFFIXES:
        raise LayoutError("Uploads must be PNG, BMP or GIF files")
    return stem


def _clean_prop(prop: dict, value):
    kind = prop["kind"]
    if kind == "number":
        return max(prop["min"], min(prop["max"], int(value)))
    if kind == "color":
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(value)):
            raise LayoutError(f"Bad colour {value!r}")
        return str(value)
    if kind in ("select", "swatch"):
        if str(value) not in prop["options"]:
            raise LayoutError(f"Bad value {value!r} for {prop['key']}")
        return str(value)
    if kind == "file":
        resolve_file(str(value))
        return str(value)
    return str(value)[:MAX_TEXT]


def validate(layout: dict, lenient=False) -> dict:
    """Returns a clean copy of a layout, or raises LayoutError.

    Lenient drops elements of unknown types, so a saved layout survives a template being removed.
    """
    try:
        elements = layout["elements"]
        if not isinstance(elements, list) or len(elements) > MAX_ELEMENTS:
            raise LayoutError("Too many elements")

        clean, seen = [], set()
        for element in elements:
            type_ = element["type"]
            schema = SCHEMA.get(type_)
            if schema is None:
                if lenient:
                    continue
                raise LayoutError(f"Unknown element type {type_!r}")

            id_ = str(element["id"])
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", id_) or id_ in seen:
                raise LayoutError(f"Bad element id {id_!r}")
            seen.add(id_)

            props = element.get("props", {})
            clean.append({
                "id": id_,
                "type": type_,
                "x": max(-WIDTH, min(WIDTH, int(element["x"]))),
                "y": max(-HEIGHT, min(HEIGHT, int(element["y"]))),
                "w": max(1, min(WIDTH, int(element["w"]))),
                "h": max(1, min(HEIGHT, int(element["h"]))),
                "hidden": bool(element.get("hidden", False)),
                "locked": bool(element.get("locked", False)),
                "props": {prop["key"]: _clean_prop(prop, props.get(prop["key"], prop["default"]))
                          for prop in schema["props"]},
            })
    except (KeyError, TypeError, AttributeError) as error:
        raise LayoutError(f"Malformed layout: {error}") from error

    if sum(1 for element in clean if element["type"] == "animation" and not element["hidden"]) > MAX_ANIMATIONS:
        raise LayoutError(f"At most {MAX_ANIMATIONS} animations")
    return {"version": VERSION, "elements": clean}


LEGACY_TOP_BAR = ("top_bar", "bar_name", "bar_time", "bar_date", "bar_usb", "bar_battery")


def upgrade_top_bar(layout: dict) -> dict:
    """Replaces the top bar's separate pieces from older layouts with one Top bar element."""
    pieces = {e.get("id"): e for e in layout.get("elements", []) if e.get("id") in LEGACY_TOP_BAR}
    bar = pieces.get("top_bar")
    if not bar or bar.get("type") != "image" or "top_bar" not in SCHEMA:
        return layout
    shown = lambda id_: "yes" if id_ in pieces and not pieces[id_].get("hidden") else "no"
    name = pieces.get("bar_name", {}).get("props", {})
    replacement = {
        "id": "top_bar", "type": "top_bar", "x": bar["x"], "y": bar["y"], "w": 256, "h": 16,
        "hidden": bool(bar.get("hidden")), "locked": bool(bar.get("locked")),
        "props": {"name": name.get("text", "{host}"), "text_colour": name.get("color", "#ffffff"),
                  "show_time": shown("bar_time"), "show_date": shown("bar_date"),
                  "show_usb": shown("bar_usb"), "show_battery": shown("bar_battery")},
    }
    elements = []
    for element in layout["elements"]:
        if element.get("id") == "top_bar":
            elements.append(replacement)
        elif element.get("id") not in LEGACY_TOP_BAR:
            elements.append(element)
    return {**layout, "elements": elements}


def upgrade_uploads(layout: dict) -> dict:
    """Uploads used to be shared as local:name. They're now in each theme's uploads folder."""
    for element in layout.get("elements", []):
        for key, value in element.get("props", {}).items():
            if isinstance(value, str) and value.startswith("local:"):
                element["props"][key] = "art:uploads/" + value[len("local:"):]
    return layout


# The boxes on the bottom screen were a pixel too wide for the grid behind them, and what's inside
# them was off centre. Version 1 layouts get the default elements they haven't moved put right.
MOVED_IN_2 = {
    "card": ((33, 217, 190, 45), (33, 217, 189, 45)),
    "disk_button": ((33, 313, 190, 45), (33, 313, 189, 45)),
    "gpu_graph": ((147, 222, 72, 36), (147, 222, 70, 35)),
    "cpu_graph": ((38, 281, 84, 26), (38, 281, 83, 24)),
    "ram_graph": ((134, 281, 84, 26), (134, 281, 83, 24)),
    "disk_bar": ((41, 336, 174, 10), (41, 336, 173, 10)),
    "disk_value": ((180, 315, 40, 12), (178, 315, 40, 12)),
}


def upgrade_alignment(layout: dict) -> dict:
    if layout.get("version", 1) >= 2:
        return layout
    for element in layout.get("elements", []):
        old, new = MOVED_IN_2.get(element.get("id"), (None, None))
        if old and tuple(element.get(key) for key in "xywh") == old:
            element.update(zip("xywh", new))
    return layout


def from_saved(layout) -> dict:
    """A theme's layout, from its file. A bad one gives the default, as it shouldn't stop the display."""
    try:
        return validate(upgrade_alignment(upgrade_top_bar(upgrade_uploads(deepcopy(layout)))), lenient=True)
    except (LayoutError, TypeError, AttributeError):
        return validate(default_layout())


from . import templates  # noqa: E402  Needs this module's SCHEMA and paths, so comes last.
templates.install()
