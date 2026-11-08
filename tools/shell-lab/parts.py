#!/usr/bin/env python3
"""Generates the measured shading parts of a DS shell SVG, to paste into the file.

    python3 tools/shell-lab/parts.py lite lid-edge      # or base-edge, slope, plate, lid
    python3 tools/shell-lab/parts.py dsi slope

Each shell's geometry is a preset below. For a new shell, add a preset and paste the output in.
The shading profiles were measured on a photo of a white DS Lite. See README.md.
"""
import argparse
import sys

PRESETS = {
    # Outline left/right, corner radius, where the lid stops above the hinge ends, the hinge's top
    # and bottom, the middle hinge part (between its seams), the base's bottom, and the lower bezel.
    "lite": dict(x0=0, x1=552, radius=19, lid_bottom=266.5, hinge_top=268.5, hinge_bottom=305.5,
                 middle=(68.9, 483.1), base_bottom=575, bezel=(135.8, 322.1, 280.4, 217.1, 4.5), plate_top=310.5),
    # Measured from a front-on render of a white DSi. Its lid runs straight along the hinge, with a dark
    # crease above the end pieces, and its plate has a wider edge.
    "dsi": dict(x0=0, x1=531, radius=17.7, lid_bottom=252.5, hinge_top=253.5, hinge_bottom=290,
                middle=(70.75, 460.2), base_bottom=544, bezel=(125.5, 305.1, 281, 217.2, 3.5), plate_top=294.7,
                plate_edge=4.75, plate_radius=6, lid_step=False),
}

# Bands from the outline inwards: (inset, width, kind, opacity). "dark" is black at that opacity,
# "light" is the rim colour. This is the lower casing half, then the seam line.
CASING = [(.4, .8, "dark", .07), (1.2, .8, "dark", .12), (2.0, .8, "dark", .18), (2.8, .8, "dark", .25),
          (3.6, .8, "dark", .4), (4.4, .7, "dark", .15)]

# The lid curves away at its edge: a bright rim, then a fade over about 16 DS pixels.
CURVE = [(7.5, .28), (8.5, .27), (9.5, .27), (10.5, .26), (11.5, .24), (12.5, .22), (13.5, .19), (14.5, .14),
         (15.5, .11), (16.5, .09), (17.5, .06), (18.5, .045), (19.5, .03), (21, .02), (23, .01)]
LID = CASING + [(5.6, 1.3, "light", 1)] + [(d, 1 if d < 20 else 2, "dark", a) for d, a in CURVE]

PLATE_EDGE = 2.4     # The plate's thin edge round the lower bezel, unless a preset says otherwise
SLOPE_SCALE = 1.15   # The slope up to the plate is the lid's fade, this much wider


def fm(value):
    return ("%.2f" % value).rstrip("0").rstrip(".")


def lid_outline_path(g, d):
    """The lid's sides and top, inset by d. Its bottom edge meets the hinge, so has no bands."""
    x0, y0, x1 = g["x0"] + d, d, g["x1"] - d
    r = max(g["radius"] - d, .01)
    bottom = fm(g["lid_bottom"])
    return (f"M{fm(x0)} {fm(y0 + r)}A{fm(r)} {fm(r)} 0 0 1 {fm(x0 + r)} {fm(y0)}H{fm(x1 - r)}"
            f"A{fm(r)} {fm(r)} 0 0 1 {fm(x1)} {fm(y0 + r)}V{bottom}M{fm(x0)} {fm(y0 + r)}V{bottom}")


def base_outline_path(g, d):
    """The lower half's sides and bottom, inset by d, starting below the hinge."""
    x0, x1, y1 = g["x0"] + d, g["x1"] - d, g["base_bottom"] - d
    r = max(g["radius"] - d, .01)
    top = fm(g["hinge_bottom"])
    return (f"M{fm(x0)} {top}V{fm(y1 - r)}A{fm(r)} {fm(r)} 0 0 0 {fm(x0 + r)} {fm(y1)}H{fm(x1 - r)}"
            f"A{fm(r)} {fm(r)} 0 0 0 {fm(x1)} {fm(y1 - r)}V{top}")


def bands(path, items, cls):
    lines = []
    for d, width, kind, opacity in items:
        if kind == "dark":
            lines.append(f'<path class="{cls}" d="{path(d)}" stroke-width="{fm(width)}" stroke-opacity="{fm(opacity)}"/>')
        else:
            lines.append(f'<path class="{cls}-rim" d="{path(d)}" stroke-width="{fm(width)}"/>')
    return "\n".join(lines)


def plate_box(g):
    bx, by, bw, bh, br = g["bezel"]
    top, edge = g["plate_top"], g.get("plate_edge", PLATE_EDGE)
    return bx - edge, top, bw + 2 * edge, by + bh + edge - top, g.get("plate_radius", br + edge)


def slope(g):
    x, y, w, h, r = plate_box(g)
    lines = []
    for d, width, _, opacity in [(d - 7.5, 1 if d < 20 else 2, "dark", a) for d, a in CURVE]:
        out = (d + width / 2) * SLOPE_SCALE
        lines.append(f'<rect class="slope" x="{fm(x - out)}" y="{fm(y - out)}" width="{fm(w + 2 * out)}" '
                     f'height="{fm(h + 2 * out)}" rx="{fm(r + out)}" stroke-width="{fm(width * SLOPE_SCALE)}" '
                     f'stroke-opacity="{opacity}"/>')
    return "\n".join(lines)


def plate(g):
    x, y, w, h, r = plate_box(g)
    return f'<rect class="plate" x="{fm(x)}" y="{fm(y)}" width="{fm(w)}" height="{fm(h)}" rx="{fm(r)}"/>'


def lid(g):
    """The lid's outline: nearly square bottom corners, stepping down to meet the middle hinge part."""
    x0, x1, r, b = g["x0"], g["x1"], g["radius"], g["lid_bottom"]
    left, right = g["middle"]
    if not g.get("lid_step", True):
        # Straight along the hinge. A dark crease above the end pieces stands in for the gap.
        h = g["hinge_top"]
        return (f'<path class="lid" d="M{fm(x0 + r)} 0H{fm(x1 - r)}A{fm(r)} {fm(r)} 0 0 1 {fm(x1)} {fm(r)}V{fm(h - 1)}'
                f'A1 1 0 0 1 {fm(x1 - 1)} {fm(h)}H{fm(x0 + 1)}A1 1 0 0 1 {fm(x0)} {fm(h - 1)}V{fm(r)}'
                f'A{fm(r)} {fm(r)} 0 0 1 {fm(x0 + r)} 0Z"/>\n'
                f'<rect class="seam" x="{fm(x0)}" y="{fm(b)}" width="{fm(left - x0)}" height="{fm(h - b)}"/>\n'
                f'<rect class="seam" x="{fm(right)}" y="{fm(b)}" width="{fm(x1 - right)}" height="{fm(h - b)}"/>')
    return (f'<path class="lid" d="M{fm(x0 + r)} 0H{fm(x1 - r)}A{r} {r} 0 0 1 {fm(x1)} {r}V{fm(b - 1)}'
            f'A1 1 0 0 1 {fm(x1 - 1)} {fm(b)}H{fm(right)}V{fm(g["hinge_top"])}H{fm(left)}V{fm(b)}'
            f'H{fm(x0 + 1)}A1 1 0 0 1 {fm(x0)} {fm(b - 1)}V{r}A{r} {r} 0 0 1 {fm(x0 + r)} 0Z"/>')


PARTS = {
    "lid-edge": lambda g: bands(lambda d: lid_outline_path(g, d), LID, "lid-edge"),
    "base-edge": lambda g: bands(lambda d: base_outline_path(g, d), CASING, "base-edge"),
    "slope": slope,
    "plate": plate,
    "lid": lid,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("shell", choices=PRESETS)
    parser.add_argument("part", choices=PARTS)
    args = parser.parse_args()
    sys.stdout.write(PARTS[args.part](PRESETS[args.shell]) + "\n")


if __name__ == "__main__":
    main()
