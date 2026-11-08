from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

ORDER = 10
BOXES = {"raised": (0, 0, 189, 45), "flat": (0, 64, 189, 109)}    # In grf/iconbox.png
PANEL = 46      # The shaded panel on the box's left, which isn't used
EDGE = 6
MIN_SIZE = 15
SCHEMA = {
    "label": "Menu button", "size": [116, 46],
    "props": [{"key": "style", "label": "Style", "kind": "select", "options": ["raised", "flat"], "default": "raised"}],
}


def box(style: str, width: int, height: int) -> Image.Image:
    """Stretches the menu's box to any size, leaving out its shaded panel."""
    from .. import layout as layouts
    return _box(str(layouts.ART_DIR), style, width, height)


@lru_cache(maxsize=32)
def _box(folder: str, style: str, width: int, height: int) -> Image.Image:
    with Image.open(Path(folder) / "grf" / "iconbox.png") as image:
        frame = np.asarray(image.convert("RGB").crop(BOXES[style]))[:, PANEL:]
    frame = np.concatenate([frame[:, :-EDGE - 1:-1], frame], axis=1)   # Mirror the right edge.

    def source(size: int, total: int) -> np.ndarray:
        """Which source line each output line uses. The middle repeats, to keep scanlines crisp."""
        edge = min(EDGE, size // 2)
        period = (total - 2 * edge) // 2 * 2
        lines = np.arange(size)
        middle = edge + (lines - edge) % period
        return np.where(lines < edge, lines, np.where(lines >= size - edge, total - (size - lines), middle))

    return Image.fromarray(frame[source(height, frame.shape[0])][:, source(width, frame.shape[1])])


def draw(canvas, element, stats, now):
    width, height = max(element["w"], MIN_SIZE), max(element["h"], MIN_SIZE)
    canvas.paste(box(element["props"]["style"], width, height), (element["x"], element["y"]))
