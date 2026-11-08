import math

from PIL import Image, ImageDraw

ORDER = 2
CLOCK_FACE = (15, 31, 112, 128)     # In background/top.png
SCHEMA = {
    "label": "Analog clock", "size": [97, 97],
    "props": [
        {"key": "face", "label": "Show face", "kind": "select", "options": ["yes", "no"], "default": "yes"},
        {"key": "hand_color", "label": "Hand colour", "kind": "color", "default": "#424242"},
        {"key": "second_color", "label": "Second hand", "kind": "color", "default": "#d30000"},
    ],
}


def draw(canvas, element, stats, now):
    from .. import widgets
    x, y, w, h = element["x"], element["y"], element["w"], element["h"]
    props = element["props"]
    if props["face"] == "yes":
        face = widgets.menu_art().crop(CLOCK_FACE)
        if face.size != (w, h):
            face = face.resize((w, h), Image.NEAREST)
        canvas.paste(face, (x, y))

    pen = ImageDraw.Draw(canvas)
    cx, cy = x + w // 2, y + h // 2
    radius = min(w, h) / 2

    def hand(angle, length, color, width):
        radians = math.radians(angle)
        pen.line((cx, cy, cx + math.sin(radians) * length, cy - math.cos(radians) * length), fill=color, width=width)

    hand((now.hour % 12 + now.minute / 60) * 30, radius * 0.45, props["hand_color"], 3)
    hand((now.minute + now.second / 60) * 6, radius * 0.68, props["hand_color"], 2)
    hand(now.second * 6, radius * 0.74, props["second_color"], 1)
    pen.rectangle((cx - 2, cy - 2, cx + 1, cy + 1), fill="#000000")
