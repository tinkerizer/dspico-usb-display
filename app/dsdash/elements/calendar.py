import calendar

import numpy as np
from PIL import Image, ImageDraw

ORDER = 3
GRID = (127, 31, 240, 128)      # In background/top.png
CELL, ROWS = 16, 5
SCHEMA = {
    "label": "Calendar", "size": [113, 97], "fixed_size": True,
    "props": [
        {"key": "today_color", "label": "Today", "kind": "color", "default": "#d30000"},
        {"key": "text_color", "label": "Text", "kind": "color", "default": "#424242"},
    ],
}


def shade(colour: str, towards, amount: float) -> str:
    values = [int(colour[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(v + (t - v) * amount) for v, t in zip(values, towards))


def today_marker(colour: str) -> Image.Image:
    """The menu's dotted box around today, in the given colour."""
    from .. import layout as layouts
    with Image.open(layouts.ART_DIR / "ui" / "marker.png") as image:
        indexes = np.asarray(image)
    palette = [shade(colour, (0, 0, 0), .4), colour, shade(colour, (255, 255, 255), .82)]
    rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in palette], dtype=np.uint8)
    return Image.fromarray(rgb[np.minimum(indexes, 2)])


def draw(canvas, element, stats, now):
    from .. import widgets
    x, y = element["x"], element["y"]
    props = element["props"]
    canvas.paste(widgets.menu_art().crop(GRID), (x, y))
    pen = ImageDraw.Draw(canvas)
    font = widgets.font(10)

    for column, letter in enumerate("SMTWTFS"):
        pen.text((x + column * CELL + CELL // 2 + 1, y + CELL // 2 + 1), letter, font=font, fill="#ffffff", anchor="mm")

    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(now.year, now.month)
    # The art has five rows; months spanning six drop whichever end today isn't in.
    if len(weeks) > ROWS:
        weeks = weeks[1:] if now.day not in weeks[0] else weeks[:-1]

    for row, week in enumerate(weeks):
        for column, day in enumerate(week):
            if day == 0:
                continue
            left, top = x + column * CELL, y + (row + 1) * CELL
            center = (left + CELL // 2 + 1, top + CELL // 2 + 1)
            if day == now.day:
                canvas.paste(today_marker(props["today_color"]), (left + 2, top + 2))
                color = shade(props["today_color"], (0, 0, 0), .55)
            else:
                color = "#d30000" if column == 0 else "#0041c3" if column == 6 else props["text_color"]
            pen.text(center, str(day), font=font, fill=color, anchor="mm")
