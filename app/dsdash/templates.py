"""Template elements: an element made of other elements, described in a JSON file. See docs/THEMES.md."""
import json
import logging
import re
from copy import deepcopy
from pathlib import Path
from typing import Dict

from . import layout as layouts

log = logging.getLogger(__name__)

KINDS = {"number", "text", "color", "select", "file", "swatch"}
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def folders():
    return [layouts.ASSETS / "templates", layouts.LOCAL_DIR / "templates"]


def _check(template: dict, source: Path) -> dict:
    for key in ("type", "label", "size", "props", "children"):
        if key not in template:
            raise ValueError(f"missing {key!r}")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", template["type"]):
        raise ValueError("type must be lower case letters, digits and _")
    for prop in template["props"]:
        if prop.get("kind") not in KINDS or "key" not in prop or "default" not in prop:
            raise ValueError(f"bad prop {prop.get('key')!r}")
        if prop["kind"] in ("select", "swatch"):
            prop["options"] = [str(option) for option in prop["options"]]
            prop["default"] = str(prop["default"])
    for child in template["children"]:
        if child.get("type") not in layouts.SCHEMA or layouts.SCHEMA[child["type"]].get("template"):
            raise ValueError(f"child type {child.get('type')!r} isn't a built-in element")
    return {**template, "source": str(source)}


def load() -> Dict[str, dict]:
    """Every template, by type. A broken file is logged and skipped. User files override built-in ones."""
    found = {}
    for folder in folders():
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                template = _check(json.loads(path.read_text(encoding="utf-8")), path)
                found[template["type"]] = template
            except (OSError, ValueError, KeyError, TypeError) as error:
                log.warning("Template %s skipped: %s", path.name, error)
    return found


def schema(template: dict) -> dict:
    return {"label": template["label"], "size": template["size"], "fixed_size": True,
            "props": template["props"], "template": True}


def _fill(value, values: dict):
    """Replaces {key} with the template's own settings. Other {tokens}, like {time}, are left for drawing."""
    if not isinstance(value, str):
        return value
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), value)


def expand(layout: dict, context: dict) -> dict:
    """The layout with each template element replaced by its children, placed relative to it.

    A setting whose value is "theme" takes the value of context[prop["theme"]], such as the theme's bar colour.
    """
    out = []
    for element in layout["elements"]:
        template = TEMPLATES.get(element.get("type"))
        if not template:
            out.append(element)
            continue
        values = {}
        for prop in template["props"]:
            value = element["props"].get(prop["key"], prop["default"])
            if value == "theme" and prop.get("theme") in context:
                value = context[prop["theme"]]
            values[prop["key"]] = value
        for index, child in enumerate(template["children"]):
            if "if" in child and values.get(child["if"]) in ("no", "", None):
                continue
            props = {p["key"]: p["default"] for p in layouts.SCHEMA[child["type"]]["props"]}
            props.update({key: _fill(value, values) for key, value in child.get("props", {}).items()})
            out.append({
                "id": f"{element['id']}.{child.get('id', index)}", "type": child["type"],
                "x": element["x"] + child["x"], "y": element["y"] + child["y"], "w": child["w"], "h": child["h"],
                "hidden": element["hidden"], "locked": True, "props": props, "from_template": element["id"],
            })
    return {**layout, "elements": out}


TEMPLATES: Dict[str, dict] = {}


def install():
    """Loads the templates and adds them to the element types the editor offers."""
    TEMPLATES.clear()
    TEMPLATES.update(load())
    for type_, template in TEMPLATES.items():
        layouts.SCHEMA[type_] = schema(template)
    return deepcopy(TEMPLATES)
