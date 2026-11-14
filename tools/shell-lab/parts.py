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
    # Measured from a front-on drawing of a black DS Lite, scaled by its screens. The plate runs up under
    # the hinge, so its top edge never shows.
    "lite": dict(x0=0, x1=552, radius=17, lid_bottom=264.5, hinge_top=270.5, hinge_bottom=307.5,
                 middle=(68.9, 483.1), base_bottom=575, bezel=(131.2, 318.2, 289.6, 225.6, 4.5), plate_top=296,
                 plate_edge=3.7),
    # Measured from a front-on render of a white DSi. Its lid runs straight along the hinge, with a dark
    # crease above the end pieces, and its plate has a wider edge.
    "dsi": dict(x0=0, x1=531, radius=17.7, lid_bottom=252.5, hinge_top=253.5, hinge_bottom=290,
                middle=(70.75, 460.2), base_bottom=544, bezel=(125.5, 305.1, 281, 217.2, 3.5), plate_top=294.7,
                plate_edge=4.75, plate_radius=6, lid_step=False, prefix="dsi-"),
}

# Bands from the outline inwards: (inset, width, kind, opacity). "dark" is black at that opacity and
# "light" is white, both over the shell's colour. This is the lower casing half, then the seam line.
CASING = [(.4, .8, "dark", .07), (1.2, .8, "dark", .12), (2.0, .8, "dark", .18), (2.8, .8, "dark", .25),
          (3.6, .8, "dark", .4), (4.4, .7, "dark", .15)]

# The lid curves away at its edge: a bright rim, then a fade over about 16 DS pixels.
CURVE = [(7.5, .28), (8.5, .27), (9.5, .27), (10.5, .26), (11.5, .24), (12.5, .22), (13.5, .19), (14.5, .14),
         (15.5, .11), (16.5, .09), (17.5, .06), (18.5, .045), (19.5, .03), (21, .02), (23, .01)]
LID = CASING + [(5.6, 1.3, "light", 1)] + [(d, 1 if d < 20 else 2, "dark", a) for d, a in CURVE]

CASING_DEPTH = 4.95  # Where the casing seam has faded out
LID_DEPTH = 24.6     # Where the lid's curve has faded out
RIM = (.75, .33, 1.02)   # The rim around its middle: where it starts, its flat top, and where it ends
RIM_OPACITY = .18
WHITE = ' stop-color="#fff"'

PLATE_EDGE = 2.4     # The plate's thin edge round the lower bezel, unless a preset says otherwise
SLOPE_SCALE = 1.15   # The slope up to the plate is the lid's fade, this much wider


def fm(value):
    return ("%.2f" % value).rstrip("0").rstrip(".")


def fo(value):
    """A gradient offset, which needs more places than a length."""
    return ("%.4f" % value).rstrip("0").rstrip(".")


def stop_list(points):
    """Gradient stops from (offset, kind, opacity): black for "dark" and white for "light"."""
    return "".join(f'<stop offset="{fo(offset)}"{WHITE if kind == "light" else ""} stop-opacity="{fm(opacity)}"/>'
                   for offset, kind, opacity in points)


def profile(items, end):
    """Bands as points across the edge: (distance in from the outline, kind, opacity), ending at 0."""
    points = [(0, "dark", items[0][3])]
    for d, width, kind, opacity in items:
        if kind == "light":
            # Black and white both reach 0 where they meet, so they never blend into grey.
            points += [(d - RIM[0], "dark", 0), (d - RIM[0], "light", 0), (d - RIM[1], "light", RIM_OPACITY),
                       (d + RIM[1], "light", RIM_OPACITY), (d + RIM[2], "light", 0), (d + RIM[2], "dark", 0)]
        elif width > 1.5:       # A wide band holds its shade across its middle
            points += [(d - .5, "dark", opacity), (d + .5, "dark", opacity)]
        else:
            points.append((d, "dark", opacity))
    return points + [(end, "dark", 0)]


def at(points, d):
    """The dark shade at distance d, between the points either side."""
    dark = [(x, o) for x, kind, o in points if kind == "dark"]
    for (x0, o0), (x1, o1) in zip(dark, dark[1:]):
        if x0 <= d <= x1:
            return o0 + (o1 - o0) * (d - x0) / (x1 - x0) if x1 > x0 else o0
    return 0


def lid_edge(g):
    """Gradients along the lid's top and sides, and round its corners. SVG has no gradient that follows
    a rounded rectangle, so the straight runs are linear and the corners radial, centred on their arcs."""
    p, x0, x1, r, bottom = g.get("prefix", ""), g["x0"], g["x1"], g["radius"], g["lid_bottom"]
    points = profile(LID, LID_DEPTH)
    run = stop_list([(d / LID_DEPTH, kind, o) for d, kind, o in points])
    inner = [(d, kind, o) for d, kind, o in points if d <= r]
    corner = stop_list([(0, "dark", at(points, r))] + [((r - d) / r, kind, o) for d, kind, o in reversed(inner)])
    t, i0, i1 = LID_DEPTH, x0 + LID_DEPTH, x1 - LID_DEPTH
    return "\n".join([
        "<!-- defs -->",
        f'<linearGradient id="{p}lid-edge" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="0" y2="{fm(t)}">{run}</linearGradient>',
        f'<linearGradient id="{p}lid-edge-l" href="#{p}lid-edge" x1="{fm(x0)}" x2="{fm(i0)}" y2="0"/>',
        f'<linearGradient id="{p}lid-edge-r" href="#{p}lid-edge" x1="{fm(x1)}" x2="{fm(i1)}" y2="0"/>',
        f'<radialGradient id="{p}lid-corner" gradientUnits="userSpaceOnUse" cx="{fm(x0 + r)}" cy="{fm(r)}" r="{fm(r)}">{corner}</radialGradient>',
        f'<radialGradient id="{p}lid-corner-r" href="#{p}lid-corner" cx="{fm(x1 - r)}"/>',
        "<!-- shapes -->",
        "<g>",
        f'<path fill="url(#{p}lid-edge)" d="M{fm(x0 + r)} 0H{fm(x1 - r)}V{fm(r)}L{fm(i1)} {fm(t)}H{fm(i0)}L{fm(x0 + r)} {fm(r)}Z"/>',
        f'<path fill="url(#{p}lid-edge-l)" d="M{fm(x0)} {fm(r)}H{fm(x0 + r)}L{fm(i0)} {fm(t)}V{fm(bottom)}H{fm(x0)}Z"/>',
        f'<path fill="url(#{p}lid-edge-r)" d="M{fm(x1)} {fm(r)}H{fm(x1 - r)}L{fm(i1)} {fm(t)}V{fm(bottom)}H{fm(x1)}Z"/>',
        f'<path fill="url(#{p}lid-corner)" d="M{fm(x0 + r)} {fm(r)}V0A{fm(r)} {fm(r)} 0 0 0 {fm(x0)} {fm(r)}Z"/>',
        f'<path fill="url(#{p}lid-corner-r)" d="M{fm(x1 - r)} {fm(r)}V0A{fm(r)} {fm(r)} 0 0 1 {fm(x1)} {fm(r)}Z"/>',
        "</g>",
    ])


def base_edge(g):
    """The casing seam down the lower half's sides and along its bottom, starting below the hinge."""
    p, x0, x1, r, top, y1 = g.get("prefix", ""), g["x0"], g["x1"], g["radius"], g["hinge_bottom"], g["base_bottom"]
    t = CASING_DEPTH
    points = profile(CASING, t)
    run = stop_list([((t - d) / t, kind, o) for d, kind, o in reversed(points)])
    cy = y1 - r
    return "\n".join([
        "<!-- defs -->",
        f'<linearGradient id="{p}base-edge" gradientUnits="userSpaceOnUse" x1="{fm(x0 + t)}" y1="0" x2="{fm(x0)}" y2="0">{run}</linearGradient>',
        f'<linearGradient id="{p}base-edge-r" href="#{p}base-edge" x1="{fm(x1 - t)}" x2="{fm(x1)}"/>',
        f'<linearGradient id="{p}base-edge-b" href="#{p}base-edge" x1="0" y1="{fm(y1 - t)}" x2="0" y2="{fm(y1)}"/>',
        f'<radialGradient id="{p}base-corner" gradientUnits="userSpaceOnUse" href="#{p}base-edge" cx="{fm(x0 + r)}" cy="{fm(cy)}" r="{fm(r)}" fr="{fm(r - t)}"/>',
        f'<radialGradient id="{p}base-corner-r" gradientUnits="userSpaceOnUse" href="#{p}base-edge" cx="{fm(x1 - r)}" cy="{fm(cy)}" r="{fm(r)}" fr="{fm(r - t)}"/>',
        "<!-- shapes -->",
        "<g>",
        f'<rect fill="url(#{p}base-edge)" x="{fm(x0)}" y="{fm(top)}" width="{fm(t)}" height="{fm(cy - top)}"/>',
        f'<rect fill="url(#{p}base-edge-r)" x="{fm(x1 - t)}" y="{fm(top)}" width="{fm(t)}" height="{fm(cy - top)}"/>',
        f'<rect fill="url(#{p}base-edge-b)" x="{fm(x0 + r)}" y="{fm(y1 - t)}" width="{fm(x1 - x0 - 2 * r)}" height="{fm(t)}"/>',
        f'<path fill="url(#{p}base-corner)" d="M{fm(x0 + r)} {fm(cy)}V{fm(y1)}A{fm(r)} {fm(r)} 0 0 1 {fm(x0)} {fm(cy)}Z"/>',
        f'<path fill="url(#{p}base-corner-r)" d="M{fm(x1 - r)} {fm(cy)}V{fm(y1)}A{fm(r)} {fm(r)} 0 0 0 {fm(x1)} {fm(cy)}Z"/>',
        "</g>",
    ])


def plate_box(g):
    bx, by, bw, bh, br = g["bezel"]
    top, edge = g["plate_top"], g.get("plate_edge", PLATE_EDGE)
    return bx - edge, top, bw + 2 * edge, by + bh + edge - top, g.get("plate_radius", br + edge)


def slope(g):
    """Shading round the plate, fading outwards from its edge: four runs and four corners."""
    p = g.get("prefix", "")
    x, y, w, h, r = plate_box(g)
    bands_out = [((d - 7.5 + (1 if d < 20 else 2) / 2) * SLOPE_SCALE, a) for d, a in CURVE]
    depth = (CURVE[-1][0] - 7.5 + 2) * SLOPE_SCALE
    stops = "".join(f'<stop offset="{fo(d / depth)}" stop-opacity="{a}"/>' for d, a in [(0, CURVE[0][1])] + bands_out + [(depth, 0)])
    size, far = depth + r, fo(r / (depth + r))
    corners = [("tl", 1, 1, x - depth, y - depth), ("tr", 0, 1, x + w - r, y - depth),
               ("bl", 1, 0, x - depth, y + h - r), ("br", 0, 0, x + w - r, y + h - r)]
    return "\n".join([
        "<!-- defs -->",
        f'<linearGradient id="{p}slope" x1="0" y1="1" x2="0" y2="0">{stops}</linearGradient>',
        f'<linearGradient id="{p}slope-b" href="#{p}slope" y1="0" y2="1"/>',
        f'<linearGradient id="{p}slope-l" href="#{p}slope" x1="1" y1="0" y2="0"/>',
        f'<linearGradient id="{p}slope-r" href="#{p}slope" x2="1" y1="0" y2="0"/>',
        *[f'<radialGradient id="{p}slope-{name}" href="#{p}slope" cx="{cx}" cy="{cy}" r="1" fr="{far}"/>' for name, cx, cy, _, _ in corners],
        "<!-- shapes -->",
        "<g>",
        f'<rect fill="url(#{p}slope)" x="{fm(x + r)}" y="{fm(y - depth)}" width="{fm(w - 2 * r)}" height="{fm(depth)}"/>',
        f'<rect fill="url(#{p}slope-b)" x="{fm(x + r)}" y="{fm(y + h)}" width="{fm(w - 2 * r)}" height="{fm(depth)}"/>',
        f'<rect fill="url(#{p}slope-l)" x="{fm(x - depth)}" y="{fm(y + r)}" width="{fm(depth)}" height="{fm(h - 2 * r)}"/>',
        f'<rect fill="url(#{p}slope-r)" x="{fm(x + w)}" y="{fm(y + r)}" width="{fm(depth)}" height="{fm(h - 2 * r)}"/>',
        *[f'<rect fill="url(#{p}slope-{name})" x="{fm(cx)}" y="{fm(cy)}" width="{fm(size)}" height="{fm(size)}"/>' for name, _, _, cx, cy in corners],
        "</g>",
    ])


def plate(g):
    x, y, w, h, r = plate_box(g)
    return f'<rect class="plastic plate" x="{fm(x)}" y="{fm(y)}" width="{fm(w)}" height="{fm(h)}" rx="{fm(r)}"/>'


def lid(g):
    """The lid's outline: nearly square bottom corners, stepping down to meet the middle hinge part."""
    x0, x1, r, b = g["x0"], g["x1"], g["radius"], g["lid_bottom"]
    left, right = g["middle"]
    if not g.get("lid_step", True):
        # Straight along the hinge. A dark crease above the end pieces stands in for the gap.
        h = g["hinge_top"]
        return (f'<path class="plastic lid" d="M{fm(x0 + r)} 0H{fm(x1 - r)}A{fm(r)} {fm(r)} 0 0 1 {fm(x1)} {fm(r)}V{fm(h - 1)}'
                f'A1 1 0 0 1 {fm(x1 - 1)} {fm(h)}H{fm(x0 + 1)}A1 1 0 0 1 {fm(x0)} {fm(h - 1)}V{fm(r)}'
                f'A{fm(r)} {fm(r)} 0 0 1 {fm(x0 + r)} 0Z"/>\n'
                f'<rect class="seam" x="{fm(x0)}" y="{fm(b)}" width="{fm(left - x0)}" height="{fm(h - b)}"/>\n'
                f'<rect class="seam" x="{fm(right)}" y="{fm(b)}" width="{fm(x1 - right)}" height="{fm(h - b)}"/>')
    return (f'<path class="plastic lid" d="M{fm(x0 + r)} 0H{fm(x1 - r)}A{r} {r} 0 0 1 {fm(x1)} {r}V{fm(b - 1)}'
            f'A1 1 0 0 1 {fm(x1 - 1)} {fm(b)}H{fm(right)}V{fm(g["hinge_top"])}H{fm(left)}V{fm(b)}'
            f'H{fm(x0 + 1)}A1 1 0 0 1 {fm(x0)} {fm(b - 1)}V{r}A{r} {r} 0 0 1 {fm(x0 + r)} 0Z"/>')


PARTS = {
    "lid-edge": lid_edge,
    "base-edge": base_edge,
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
