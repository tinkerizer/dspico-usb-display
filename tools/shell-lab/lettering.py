#!/usr/bin/env python3
"""Turns text into an SVG path in Varela Round, for shell lettering such as "MIC.".

    python3 tools/shell-lab/lettering.py "MIC." --cap 6.1 --x 285.5 --baseline 289.1 --squeeze .9

Needs fontTools (`pip install fonttools`) and VarelaRound-Regular.ttf (SIL Open Font License), from
https://github.com/google/fonts/raw/main/ofl/varelaround/VarelaRound-Regular.ttf. Pass --font if it's
not beside this script. Sizes are in DS pixels: --cap is the capital height.
"""
import argparse
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("text")
    parser.add_argument("--cap", type=float, required=True, help="capital height")
    parser.add_argument("--x", type=float, required=True, help="left edge")
    parser.add_argument("--baseline", type=float, required=True)
    parser.add_argument("--squeeze", type=float, default=1.0, help="horizontal scale, below 1 narrows")
    parser.add_argument("--tracking", type=float, default=0.0, help="extra space between letters")
    parser.add_argument("--font", default=str(Path(__file__).with_name("VarelaRound-Regular.ttf")))
    args = parser.parse_args()

    font = TTFont(args.font)
    glyphs, cmap, metrics = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    scale = args.cap / font["OS/2"].sCapHeight
    pen = SVGPathPen(glyphs, ntos=lambda v: ("%.2f" % v).rstrip("0").rstrip("."))
    advance = 0.0
    for char in args.text:
        name = cmap[ord(char)]
        x = args.x + advance * scale * args.squeeze
        glyphs[name].draw(TransformPen(pen, (scale * args.squeeze, 0, 0, -scale, x, args.baseline)))
        advance += metrics[name][0] + args.tracking / scale
    print(f"<!-- {advance * scale * args.squeeze:.1f} wide -->")
    print(f'<path class="ink" d="{pen.getCommands()}"/>')


if __name__ == "__main__":
    main()
