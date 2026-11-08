#!/usr/bin/env python3
"""Renders a shell to a PNG, optionally beside a reference image at the same scale.

    python render.py lite out.png --colour "#ececec" --label "#9b8f86" --zoom 2
    python render.py dsi out.png --compare refs/dsi-white.png --scale 1.918 --offset=-2.25,0.111

Runs in Chrome through Playwright, so on this setup use the Windows test venv that
`tools/check --browser` makes. With --compare, the reference is placed so its DS pixels line up
with the render's, on the left.
"""
import argparse
import re
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

WEB = Path(__file__).resolve().parent.parent.parent / "app" / "dsdash" / "web"
FILES = {"lite": WEB / "shell.svg", "dsi": WEB / "shell-dsi.svg"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("shell", choices=FILES)
    parser.add_argument("output")
    parser.add_argument("--colour", default="#3d3d3d")
    parser.add_argument("--label", default="#e8e8e8")
    parser.add_argument("--zoom", type=float, default=2)
    parser.add_argument("--compare", help="reference image to put beside the render")
    parser.add_argument("--scale", type=float, help="reference image pixels per DS pixel")
    parser.add_argument("--offset", default="0,0", help="reference DS x,y offset, as in measure.py")
    args = parser.parse_args()

    svg = FILES[args.shell].read_text()
    _, _, width, height = (float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split())
    page = (f"<html><body style='margin:0;background:#888'><div style='--ds-color:{args.colour};"
            f"--ds-label:{args.label};width:{width}px'>{svg}</div></body></html>")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        tab = browser.new_page(viewport={"width": int(width), "height": int(height)}, device_scale_factor=args.zoom)
        tab.set_content(page)
        tab.wait_for_timeout(300)
        tab.screenshot(path=args.output)
        browser.close()

    if args.compare:
        render = Image.open(args.output).convert("RGB")
        reference = Image.open(args.compare).convert("RGBA")
        grey = Image.new("RGBA", reference.size, (136, 136, 136, 255))
        reference = Image.alpha_composite(grey, reference).convert("RGB")
        k = args.zoom / args.scale
        reference = reference.resize((round(reference.width * k), round(reference.height * k)), Image.LANCZOS)
        ox, oy = (float(v) for v in args.offset.split(","))
        placed = Image.new("RGB", render.size, (136, 136, 136))
        placed.paste(reference, (round(ox * args.zoom), round(oy * args.zoom)))
        both = Image.new("RGB", (render.width * 2 + 10, render.height), (255, 0, 255))
        both.paste(placed, (0, 0))
        both.paste(render, (render.width + 10, 0))
        both.save(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
