from PIL import ImageDraw

ORDER = 9
SCHEMA = {
    "label": "Panel", "size": [100, 60],
    "props": [
        {"key": "fill", "label": "Fill", "kind": "color", "default": "#fbfbfb"},
        {"key": "outline", "label": "Outline", "kind": "color", "default": "#828282"},
    ],
}


def draw(canvas, element, stats, now):
    x, y, w, h = element["x"], element["y"], element["w"], element["h"]
    ImageDraw.Draw(canvas).rectangle((x, y, x + w - 1, y + h - 1), fill=element["props"]["fill"],
                                     outline=element["props"]["outline"])
