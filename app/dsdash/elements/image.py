from PIL import Image

ORDER = 1
SCHEMA = {
    "label": "Image", "size": [64, 64],
    "props": [
        {"key": "file", "label": "Image", "kind": "file", "default": "art:quickmenu/topbg.png"},
        {"key": "crop_x", "label": "Crop X", "kind": "number", "default": 0, "min": 0, "max": 2048},
        {"key": "crop_y", "label": "Crop Y", "kind": "number", "default": 0, "min": 0, "max": 2048},
        {"key": "crop_w", "label": "Crop width", "kind": "number", "default": 0, "min": 0, "max": 2048},
        {"key": "crop_h", "label": "Crop height", "kind": "number", "default": 0, "min": 0, "max": 2048},
        {"key": "lock_aspect", "label": "Lock aspect ratio", "kind": "select", "options": ["yes", "no"], "default": "yes"},
        {"key": "pixel_lock", "label": "Lock to pixel scale", "kind": "select", "options": ["yes", "no"], "default": "no"},
    ],
}


def draw(canvas, element, stats, now):
    from .. import widgets
    props = element["props"]
    image = widgets.load_art(props["file"])
    if props["crop_w"] and props["crop_h"]:
        x, y = props["crop_x"], props["crop_y"]
        image = image.crop((x, y, x + props["crop_w"], y + props["crop_h"]))
    if image.size != (element["w"], element["h"]):
        image = image.resize((element["w"], element["h"]), Image.NEAREST)
    canvas.paste(image, (element["x"], element["y"]), image)
