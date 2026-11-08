#!/usr/bin/env python3
"""Traces dark marks in part of a reference image into an SVG path in DS pixels, such as printed icons.

    python3 tools/shell-lab/trace.py refs/dsi-white.png --scale 1.918 --offset=-2.25,0.111 --box 34,446,110,480

--box is left,top,right,bottom in image pixels. Anything darker than --threshold is traced, after the
crop is enlarged so the curves come out smooth. The DSi's wireless, charging and power icons were
made this way. Needs Pillow, NumPy and potracer (`pip install potracer`).
"""
import argparse

import numpy as np
import potrace
from PIL import Image


def fm(value):
    return ("%.2f" % value).rstrip("0").rstrip(".")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--scale", type=float, required=True, help="image pixels per DS pixel")
    parser.add_argument("--offset", default="0,0", help="DS x,y offset")
    parser.add_argument("--box", required=True)
    parser.add_argument("--threshold", type=int, default=185)
    parser.add_argument("--enlarge", type=int, default=8)
    args = parser.parse_args()

    image = Image.open(args.image).convert("RGBA")
    flat = Image.new("RGBA", image.size, (255, 255, 255, 255))
    image = Image.alpha_composite(flat, image).convert("RGB")
    x0, y0, x1, y1 = (int(v) for v in args.box.split(","))
    k = args.enlarge
    crop = image.crop((x0, y0, x1, y1)).resize(((x1 - x0) * k, (y1 - y0) * k), Image.LANCZOS)
    ink = np.asarray(crop).astype(int).mean(2) < args.threshold
    # potracer traces the False areas, so it's given the background.
    curves = potrace.Bitmap(~ink).trace(turdsize=20, alphamax=1.0, opttolerance=0.2)
    ox, oy = (float(v) for v in args.offset.split(","))

    def point(p):
        return f"{fm((x0 + p.x / k) / args.scale + ox)} {fm((y0 + p.y / k) / args.scale + oy)}"

    d = []
    for curve in curves:
        d.append("M" + point(curve.start_point))
        for segment in curve.segments:
            if segment.is_corner:
                d.append("L" + point(segment.c) + "L" + point(segment.end_point))
            else:
                d.append("C" + point(segment.c1) + " " + point(segment.c2) + " " + point(segment.end_point))
        d.append("Z")
    print(f'<path class="ink" d="{"".join(d)}"/>')


if __name__ == "__main__":
    main()
