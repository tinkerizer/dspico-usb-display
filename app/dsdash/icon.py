"""Draws the app icon, so there is no binary file to keep in step."""
from PIL import Image, ImageDraw

SHELL = (72, 76, 88, 255)
SCREEN = (214, 228, 240, 255)
HINGE = (46, 49, 58, 255)


def draw_icon(size: int = 64, status=None) -> Image.Image:
    """A small clamshell handheld, with an optional status dot in the corner."""
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 3, 52, 61), 6, fill=SHELL)
    draw.rectangle((12, 30, 52, 34), fill=HINGE)
    draw.rectangle((18, 8, 46, 27), fill=SCREEN)
    draw.rectangle((18, 37, 46, 56), fill=SCREEN)
    if status:
        draw.ellipse((38, 38, 62, 62), fill=status, outline=(255, 255, 255, 255), width=2)
    return image.resize((size, size), Image.LANCZOS)


def save_ico(path: str):
    draw_icon(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
