ORDER = 11
draw = None     # GIFs are played by the DS itself. See device.py.
SCHEMA = {
    "label": "Animation", "size": [100, 68],
    "props": [
        {"key": "file", "label": "GIF", "kind": "file", "default": "art:uploads/cloud.gif"},
        {"key": "crop_x", "label": "Crop X", "kind": "number", "default": 0, "min": 0, "max": 2048},
        {"key": "crop_y", "label": "Crop Y", "kind": "number", "default": 0, "min": 0, "max": 2048},
        {"key": "crop_w", "label": "Crop width", "kind": "number", "default": 0, "min": 0, "max": 2048},
        {"key": "crop_h", "label": "Crop height", "kind": "number", "default": 0, "min": 0, "max": 2048},
        {"key": "lock_aspect", "label": "Lock aspect ratio", "kind": "select", "options": ["yes", "no"], "default": "yes"},
        {"key": "pixel_lock", "label": "Lock to pixel scale", "kind": "select", "options": ["yes", "no"], "default": "no"},
    ],
}
