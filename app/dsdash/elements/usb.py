ORDER = 7
SCHEMA = {"label": "USB status", "size": [12, 7], "props": []}
ICON = ("......######", "......#....#", "#######.##.#", "#######....#", "#######.##.#", "......#....#", "......######")


def draw(canvas, element, stats, now):
    """A plug, green while the DS is connected and red when it isn't."""
    colour = (70, 230, 90) if stats.usb_connected else (255, 70, 70)
    for y, row in enumerate(ICON):
        for x, pixel in enumerate(row):
            if pixel == "#":
                canvas.putpixel((element["x"] + x, element["y"] + y), colour)
