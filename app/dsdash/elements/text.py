from PIL import ImageDraw

ORDER = 4
SIZES = ["8", "10", "12", "20", "30"]
SCHEMA = {
    "label": "Text", "size": [80, 12],
    "props": [
        {"key": "text", "label": "Text", "kind": "text", "default": "{time}"},
        {"key": "size", "label": "Size", "kind": "select", "options": SIZES, "default": "10"},
        {"key": "color", "label": "Colour", "kind": "color", "default": "#424242"},
        {"key": "align", "label": "Align", "kind": "select", "options": ["left", "center", "right"], "default": "left"},
    ],
}


def draw(canvas, element, stats, now):
    from .. import widgets
    props = element["props"]
    text = widgets.expand_tokens(props["text"], widgets.token_values(stats, now))
    x, y, w = element["x"], element["y"], element["w"]
    anchor, position = {"left": ("la", x), "center": ("ma", x + w // 2), "right": ("ra", x + w)}[props["align"]]
    ImageDraw.Draw(canvas).text((position, y), text, font=widgets.font(int(props["size"])), fill=props["color"],
                                anchor=anchor)
