from . import text

ORDER = 8
WARM, HOT = 70, 85      # Celsius
SCHEMA = {
    "label": "Temperature", "size": [62, 12],
    "props": [
        {"key": "text", "label": "Label", "kind": "text", "default": "TEMP "},
        {"key": "size", "label": "Size", "kind": "select", "options": text.SIZES, "default": "10"},
        {"key": "color", "label": "Colour", "kind": "color", "default": "#424242"},
    ],
}


def draw(canvas, element, stats, now):
    """Text that changes colour as it heats up, so it reads at a glance."""
    temperature = stats.temperature
    colour = element["props"]["color"]
    if temperature is not None and temperature >= HOT:
        colour = "#d30000"
    elif temperature is not None and temperature >= WARM:
        colour = "#e07000"
    label = element["props"]["text"] + "{temp}"
    text.draw(canvas, {**element, "props": {"align": "left", **element["props"], "text": label, "color": colour}}, stats, now)
