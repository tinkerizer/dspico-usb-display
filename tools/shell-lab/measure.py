#!/usr/bin/env python3
"""Prints where brightness changes along a row or column of a reference image, in DS pixels.

    python3 tools/shell-lab/measure.py refs/dsi-white.png --scale 1.918 --offset=-2.25,0.111 row 790
    python3 tools/shell-lab/measure.py refs/dsi-white.png --scale 1.918 --offset=-2.25,0.111 col 512 --from 420 --to 640

A DS pixel is image pixel / scale + offset. Get the scale from something of known size, such as a
screen's active area, which is 256 DS pixels wide. Each line shows the image pixel, the DS pixel,
and the brightness either side, so bezels, seams and outlines show up as runs of changes.
Needs Pillow and NumPy.
"""
import argparse

import numpy as np
from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image")
    parser.add_argument("--scale", type=float, required=True, help="image pixels per DS pixel")
    parser.add_argument("--offset", default="0,0", help="DS x,y offset")
    parser.add_argument("direction", choices=("row", "col"))
    parser.add_argument("at", type=int, help="the row's y or the column's x, in image pixels")
    parser.add_argument("--from", dest="start", type=int, default=0)
    parser.add_argument("--to", dest="end", type=int)
    parser.add_argument("--step", type=int, default=6, help="smallest brightness change to show")
    args = parser.parse_args()

    image = Image.open(args.image).convert("RGBA")
    pixels = np.asarray(image).astype(int)
    grey = pixels[..., :3].mean(2)
    grey[pixels[..., 3] < 128] = -1     # transparent, shown as -1
    ox, oy = (float(v) for v in args.offset.split(","))
    line = grey[args.at, :] if args.direction == "row" else grey[:, args.at]
    end = args.end or len(line)
    offset = ox if args.direction == "row" else oy
    for i in range(max(args.start, 1), end):
        if abs(line[i] - line[i - 1]) >= args.step:
            print(f"image {i:5}  DS {i / args.scale + offset:7.2f}   {int(line[i - 1]):4} > {int(line[i])}")


if __name__ == "__main__":
    main()
