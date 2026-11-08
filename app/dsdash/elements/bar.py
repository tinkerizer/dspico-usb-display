from PIL import ImageDraw

ORDER = 5
METRICS = ["cpu", "ram", "disk", "gpu"]
SCHEMA = {
    "label": "Bar", "size": [150, 8],
    "props": [
        {"key": "metric", "label": "Shows", "kind": "select", "options": METRICS, "default": "cpu"},
        {"key": "color", "label": "Colour", "kind": "color", "default": "#0041c3"},
    ],
}


def draw(canvas, element, stats, now):
    x, y, w, h = element["x"], element["y"], element["w"], element["h"]
    percent = {"cpu": stats.cpu_percent, "gpu": stats.gpu_percent or 0, "ram": stats.ram_percent,
               "disk": stats.disk_percent}[element["props"]["metric"]]
    pen = ImageDraw.Draw(canvas)
    pen.rectangle((x, y, x + w - 1, y + h - 1), fill="#ffffff", outline="#828282")
    filled = int((w - 2) * min(percent, 100) / 100)
    if filled > 0:
        pen.rectangle((x + 1, y + 1, x + filled, y + h - 2), fill=element["props"]["color"])
