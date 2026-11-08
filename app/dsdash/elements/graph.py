from PIL import ImageDraw

ORDER = 6
HISTORIES = ["cpu", "ram", "net", "gpu"]
SCHEMA = {
    "label": "Graph", "size": [110, 40],
    "props": [
        {"key": "metric", "label": "Shows", "kind": "select", "options": HISTORIES, "default": "cpu"},
        {"key": "color", "label": "Colour", "kind": "color", "default": "#96b4e6"},
    ],
}


def draw(canvas, element, stats, now):
    x, y, w, h = element["x"], element["y"], element["w"], element["h"]
    metric = element["props"]["metric"]
    history = list({"cpu": stats.cpu_history, "gpu": stats.gpu_history, "ram": stats.ram_history,
                    "net": stats.net_history}[metric])[-w:]
    peak = (max(history, default=0) or 1) if metric == "net" else 100
    pen = ImageDraw.Draw(canvas)
    base = y + h - 1
    for index, value in enumerate(history):
        column = x + w - len(history) + index
        pen.line((column, base, column, base - value * (h - 1) / peak), fill=element["props"]["color"])
