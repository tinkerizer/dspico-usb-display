# Shell lab

Tools for drawing the DS shells: `app/dsdash/web/shell.svg` (DS Lite) and `shell-dsi.svg` (DSi).

```bash
tools/shell-lab/run                              # live preview at http://127.0.0.1:8770/
python3 tools/shell-lab/parts.py lite slope      # generate measured shading, see below
python3 tools/shell-lab/lettering.py "MIC." --cap 6.1 --x 285.5 --baseline 289.1 --squeeze .9
```

## The live preview

Edit the SVG in your editor and save, and the page redraws within half a second.

- **Coordinates:** the SVG is drawn in DS pixels, so each screen is exactly 256×192. The panel
  shows the cursor's position in those units.
- **Finding the code:** hovering shows the element under the cursor and its attributes, so you
  can search for it in the file. Click an element to pin it.
- **References:** put photos in `refs/`, which is git-ignored, as photos are rarely ours to
  publish. Shift-drag moves the image, and Shift-wheel scales it. "Hold to compare" shows only the
  photo. "Difference" blending turns parts that line up black. Each image keeps its own
  alignment, and `refs/<image name>.json` gives a starting one, as `{"s": scale, "x": …, "y": …}`.

## Generated parts

`parts.py` prints SVG to paste into a shell. Each shell is a preset at the top of the file, with its
outline, corner radius, hinge and lower bezel. For a new shell, add a preset. Parts:

| Part | What it is |
|---|---|
| `lid` | The lid's outline. Bottom corners nearly square, stepping down to meet the middle hinge part |
| `lid-edge` | Bands on the lid's sides and top: casing seam, bright rim, then the curved-edge fade |
| `base-edge` | Bands on the lower half's sides and bottom: the casing seam |
| `plate` | The raised plate the lower screen sits in |
| `slope` | Shading round the plate |

Both shells are generated from their presets, so regenerating reproduces them exactly.

## Measuring tools

These work on a reference image given its scale (image pixels per DS pixel) and offset, so that
DS pixel = image pixel / scale + offset. For the DSi render that's `--scale 1.918 --offset=-2.25,0.111`.
Write a negative offset with `=`, as above.

| Tool | What it does |
|---|---|
| `measure.py` | Prints brightness changes along a row or column, in DS pixels: bezels, seams and outlines |
| `trace.py` | Traces dark marks in part of the image into an SVG path, for printed icons |
| `render.py` | Renders a shell to a PNG in any colour, optionally beside the reference at the same scale |

`measure.py` and `trace.py` need Pillow and NumPy, and `trace.py` also needs potracer. `render.py`
uses Chrome through Playwright, so on this setup run it with the Windows test venv that
`tools/check --browser` makes.

`lettering.py` turns text into outlines, since the viewer may not have the font. It needs fontTools
and `VarelaRound-Regular.ttf` beside it, which is git-ignored. Download links are in the script.

## What a DS shell looks like

These rules came from comparing against photos of real DS Lites. Both shells follow them, and a
new one should too.

**Lid (top half)**
- **Curved edge:** the lid curves away at its sides and top. From the outline inwards: a band
  that's part of the other casing half, a dark seam line about 3.6 DS pixels in, a bright rim, then
  a fade from about 28% darker to nothing over about 16 DS pixels. The bottom edge has none of this.
- **Bottom:** the bottom corners are nearly square (radius 1). Above the hinge's end pieces the lid
  stops 2 DS pixels short, leaving a gap. Above the middle hinge part it steps down to meet it, and
  the step is exactly the middle part's width, so the gap continues over the black seams.
- **Top bezel:** just the panel and one outline. No rim and no raised plate: it differs from the
  lower one.
- **Rubber strips:** one at each top corner, standing up along the side, about 4.5 × 38 DS pixels.
  They sit inside the curved edge, against the seam, level with the top pads.

**Hinge**
- **Height:** the middle part and the end pieces are the same height.
- **Mic:** the hole is centred under the screen. On the Lite it's 4 × 13.2 DS pixels, with
  "MIC." beside it: capitals 6.1 high, 19.2 wide, squeezed to 90%.

**Lower half**
- **Seam:** the same casing seam and band runs down the sides and along the bottom, but starts
  below the hinge. Beside the hinge's rounded ends the shell is flat.
- **Raised plate:** the lower screen sits in it. The plate is one piece of the shell plastic, in
  the shell colour, not lighter. It shows as a strip above the bezel, slightly shorter than the
  bezel's top border, and a thin edge of 2.4 DS pixels round the rest of it.
- **Plate corners:** the strip starts a few pixels below the hinge, and its corners have the
  bezel's radius plus the edge width.
- **Lower bezel:** flush with the plate, with only a thin dark outline.
- **Slope:** the shell slopes gently up to the plate. Shade it with the lid's fade, about 15%
  wider. It's a gradient only, with no extra shadow below, and must never look like a hard step.

**Sizes measured so far**

| | DS Lite | DSi |
|---|---|---|
| Outline | 552 × 575, radius 19 | 531 × 544, radius 17.7 |
| Bezel round the glass | about 12.2 | 9 to a black LCD frame, then 3.6 to the screen, top and bottom |
| Hinge | 268.5 to 305.5 | 253.5 to 290 |
| Raised plate edge | 2.4 | 4.75, with a 10.4 strip |

## Measuring from a photo

1. **Scale:** find it from something of known size. The screen glass is 256 DS pixels wide, and the
   Lite's speaker holes are 21 apart.
2. **Profiles:** sample brightness along a row or column across an edge, and read off the shade
   and width of each band. Express them relative to the plain shell colour, as a percentage
   darker or lighter, so they work on any shell colour.
3. **Check side by side:** compare a render of the shell with the photo at the same scale. The
   preview's "Difference" blend does this quickly.

The DSi was measured from a front-on render of a white DSi (`refs/dsi-white.png`), straight from the
image at 1.918 image pixels per DS pixel, with its icons traced from it.

Mind which photos you trust. Of the photos used here, a sharp photo of a white DS Lite was the most
accurate. A stock render had wider bezels (16 against 12).

## Things to keep

- **Colours:** use `color-mix(in srgb, var(--base), …)` or black and white at an opacity, never a
  fixed colour, so every shell colour works. Test with a dark and a light colour.
- **No blur filters on large shapes:** build soft shading from nested outlines or stacked
  translucent shapes, as `parts.py` does. Blur filters are slow when Chrome renders without a GPU.
- **Fixed parts:** the screens (`.glass`) and the hinge must stay where they are, as the live preview
  is laid over them. Their positions are in `SHELLS` in `app.js`.
- **Lettering:** text is outlines in Varela Round (SIL Open Font License).
- **Pressable controls:** these are `<g class="press">` groups. Keep the group when editing
  what's inside.
