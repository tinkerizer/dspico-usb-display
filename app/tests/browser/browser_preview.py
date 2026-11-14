"""The DS on screen: its size, its pixels, the shelf, and animations over the seam.

Fractional DPRs such as 1.25 aren't tested. Pixels are known not to be exact there.
"""
import math

import numpy as np

import harness
from harness import (HINGE, NEXT_PAINT, SEAM, W, BrowserCase, black_frame, changed, decode, pattern_frame,
                     real_scale_page, set_window, wait_ready)

SIZES = [(1920, 1060), (1920, 1080), (1366, 768), (1280, 720), (1600, 900), (2560, 1440), (1000, 800)]
RECTS = """() => Object.fromEntries(Object.entries({
  top: '.lcd.top', bottom: '.lcd.bottom', screens: '#screens', dock: '.edit-dock', console: '.console', bar: '.topbar', edit: '.view-dock', panel: '#panel',
}).map(([name, selector]) => {
  const { left, top, right, bottom, width, height } = document.querySelector(selector).getBoundingClientRect();
  return [name, { left, top, right, bottom, width, height }];
}))"""
# Window sizes, and the device pixels per DS pixel they should give.
SIZES_AT_DPR_1 = [(1920, 1060, 1), (1600, 1000, 1), (2560, 1560, 2)]
WINDOWS_AT_DPR_2 = [(1600, 900, 2), (1280, 720, 2), (2100, 1200, 3)]
CORNER = 4      # DS pixels. The bottom LCD has rounded corners, like the real one.
# Chrome lays out in 1/64ths of a CSS pixel, so percentages can land one step off.
# That can't move a painted pixel, and PixelTests compares those exactly.
LAYOUT_STEP = 1 / 64


def resize(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.wait_for_function("([w, h]) => innerWidth === w && innerHeight === h", arg=[width, height])
    page.evaluate(NEXT_PAINT)


def hide_chrome(page):
    """Keeps the page's bars out of screenshots. They don't change its layout."""
    page.add_style_tag(content=".dock, .topbar { visibility: hidden; }")


def screens_shot(page) -> np.ndarray:
    page.evaluate("showScreens()")
    page.evaluate(NEXT_PAINT)
    rect = page.evaluate(RECTS)["screens"]
    dpr = page.evaluate("devicePixelRatio")
    # A clip on half a CSS pixel loses a row, so take whole ones and cut it down after.
    x, y = math.floor(rect["left"]), math.floor(rect["top"])
    clip = {"x": x, "y": y, "width": math.ceil(rect["right"]) - x, "height": math.ceil(rect["bottom"]) - y}
    shot = decode(page.screenshot(clip=clip))
    left, top = round((rect["left"] - x) * dpr), round((rect["top"] - y) * dpr)
    return shot[top:top + round(rect["height"] * dpr), left:left + round(rect["width"] * dpr)]


class GeometryTests(BrowserCase):
    def check_sizes(self, dpr):
        page = self.open(dpr=dpr)
        for width, height in SIZES:
            with self.subTest(width=width, height=height, dpr=dpr):
                resize(page, width, height)
                r = page.evaluate(RECTS)
                top, bottom = r["top"], r["bottom"]
                pixels = top["width"] / W * dpr

                self.assertEqual(pixels, round(pixels), "A DS pixel isn't whole device pixels")
                self.assertGreaterEqual(pixels, 1)
                for lcd in (top, bottom):
                    self.assertAlmostEqual(lcd["height"], lcd["width"] * 3 / 4, delta=LAYOUT_STEP)
                    self.assertAlmostEqual(lcd["width"], W * pixels / dpr, delta=LAYOUT_STEP)
                    self.assertAlmostEqual(lcd["left"] * dpr, round(lcd["left"] * dpr), delta=LAYOUT_STEP * dpr)
                    self.assertAlmostEqual(lcd["top"] * dpr, round(lcd["top"] * dpr), delta=LAYOUT_STEP * dpr)
                self.assertEqual(top["left"], bottom["left"])
                self.assertAlmostEqual(bottom["top"] - top["bottom"], HINGE * pixels / dpr, delta=2 * LAYOUT_STEP)

    def test_screens_and_hinge_at_dpr_1(self):
        self.check_sizes(1)

    def test_screens_and_hinge_at_dpr_2(self):
        self.check_sizes(2)

    def test_sizes_are_right_on_a_fresh_load_too(self):
        page = self.open(width=1920, height=1060, dpr=2)
        r = page.evaluate(RECTS)
        pixels = r["top"]["width"] / W * 2
        self.assertEqual(pixels, round(pixels))
        self.assertAlmostEqual(r["bottom"]["top"] - r["top"]["bottom"], HINGE * pixels / 2, delta=2 * LAYOUT_STEP)


class PixelTests(BrowserCase):
    def assert_paints(self, shot, wanted):
        pixels = shot.shape[1] // W
        self.assertEqual(shot.shape[1], W * pixels)
        self.assertEqual(shot.shape[0], (2 * SEAM + HINGE) * pixels)

        big = wanted.repeat(pixels, 0).repeat(pixels, 1)
        split = SEAM * pixels
        bottom = (SEAM + HINGE) * pixels
        bad_top = (shot[:split] != big[:split]).any(axis=2)
        bad_bottom = (shot[bottom:] != big[split:]).any(axis=2)
        corner = CORNER * pixels
        for rows in (slice(0, corner), slice(-corner, None)):
            for columns in (slice(0, corner), slice(-corner, None)):
                bad_bottom[rows, columns] = False
        self.assertEqual(int(bad_top.sum()), 0, "Top LCD differs from the frame")
        self.assertEqual(int(bad_bottom.sum()), 0, "Bottom LCD differs from the frame")

    def test_lcds_paint_the_frame_exactly_at_dpr_1(self):
        frame = pattern_frame()
        hidden = changed(lambda e: e["cloud"].update(hidden=True))
        page = self.open(layout=hidden, frame=frame)
        hide_chrome(page)
        for width, height, pixels in SIZES_AT_DPR_1:
            with self.subTest(width=width, height=height):
                resize(page, width, height)
                shot = screens_shot(page)
                self.assertEqual(shot.shape[1], W * pixels)
                self.assert_paints(shot, decode(frame))

    def test_lcds_paint_the_frame_exactly_at_dpr_2(self):
        """A real scale factor, as emulated DPR 2 isn't exact for odd multiples. Those sit on
        half CSS pixels, and it snaps them to whole ones before scaling. Real screens don't."""
        frame = pattern_frame()
        harness.app.set_layout(changed(lambda e: e["cloud"].update(hidden=True)))
        real, page = real_scale_page(*WINDOWS_AT_DPR_2[0][:2], 2, frame)
        self.addCleanup(real.close)
        page.goto(harness.url)
        wait_ready(page)
        hide_chrome(page)
        for index, (width, height, pixels) in enumerate(WINDOWS_AT_DPR_2):
            with self.subTest(width=width, height=height):
                if index:
                    set_window(page, width, height)
                shot = screens_shot(page)
                self.assertEqual(shot.shape[1], W * pixels)
                self.assert_paints(shot, decode(frame))


class ShelfTests(BrowserCase):
    def test_what_is_under_the_ds_can_be_reached_and_the_page_never_scrolls_sideways(self):
        page = self.open()
        for editing, name in ((False, "edit"), (True, "dock")):
            page.evaluate("on => setEditing(on)", editing)
            for width, height in SIZES:
                with self.subTest(width=width, height=height, editing=editing):
                    resize(page, width, height)
                    self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
                    page.evaluate("on => document.querySelector(on ? '.edit-dock' : '.view-dock').scrollIntoView({ block: 'end' })", editing)
                    page.evaluate(NEXT_PAINT)
                    under = page.evaluate(RECTS)[name]
                    self.assertGreater(under["height"], 0)
                    self.assertGreaterEqual(under["top"], 0)
                    self.assertLessEqual(under["bottom"], height + 0.5)

    def test_tools_show_only_in_the_editor_just_below_the_screens(self):
        page = self.open(width=1920, height=1060)
        self.assertFalse(page.locator(".edit-dock").is_visible())
        self.assertTrue(page.locator("#editButton").is_visible())
        label = page.locator("#editButton .tool-label")
        self.assertEqual((label.text_content(), page.locator("#editButton .icon").bounding_box()["width"]), ("Edit", 45))
        page.click("#editButton")
        r = page.evaluate(RECTS)
        self.assertFalse(page.locator("#editButton").is_visible())
        self.assertFalse(page.locator("#panel").is_visible())
        gap = r["dock"]["top"] - r["console"]["bottom"]
        self.assertGreater(gap, 0, "The tools touch the screens")
        self.assertLess(gap, 20, "The tools are too far from the screens")

    def test_settings_sit_beside_the_ds_and_change_the_theme(self):
        page = self.open(width=1920, height=1060)
        r = page.evaluate(RECTS)
        self.assertEqual((r["panel"]["right"], r["panel"]["top"], r["panel"]["bottom"]), (1920, r["bar"]["bottom"], 1060))
        self.assertLess(r["console"]["right"], r["panel"]["left"])
        cards = page.locator(".theme-card")
        self.assertGreaterEqual(cards.count(), 2)
        self.assertEqual(page.locator(".theme-card[aria-selected=true]").get_attribute("data-theme"), "Classic")
        # Put back by hand: resetting Classic would also drop the layout and images other tests use.
        self.addCleanup(page.evaluate, "async () => { const t = (await api('/api/themes')).themes.Classic; await changeDsTheme({ action: 'colours', theme: { ...t, boost: 0 } }); }")
        page.locator("#dsThemeBoost").fill("40")
        page.wait_for_function("async () => (await api('/api/themes')).themes.Classic.boost === 40")
        self.assertEqual(page.text_content("#dsThemeDelete"), "Reset Classic")
        self.assertTrue(page.is_enabled("#dsThemeDelete"))

    def test_grid_runs_through_the_tile_cells(self):
        page = self.open(width=1920, height=1060)
        self.addCleanup(page.evaluate, "setShellModel('lite')")
        places = set()
        for editing, fill, scroll, shell in ((True, False, 0, "lite"), (True, False, 100000, "lite"), (True, True, 0, "lite"),
                                             (False, False, 0, "lite"), (False, False, 0, "dsi")):
            page.evaluate("([editing, fill]) => { setEditing(editing); setFill(fill); }", [editing, fill])
            page.evaluate("shell => setShellModel(shell)", shell)
            page.evaluate("y => window.scrollTo(0, y)", scroll)
            page.evaluate(NEXT_PAINT)
            tiles, grid = page.evaluate("""() => {
              const style = getComputedStyle(document.documentElement);
              return [[...document.querySelectorAll('.tile, .dock .shell-swatch')].filter(n => n.offsetParent).map(n => { const b = n.getBoundingClientRect(); return [b.left + scrollX, b.top + scrollY]; }),
                      [parseFloat(style.getPropertyValue('--grid-x')), parseFloat(style.getPropertyValue('--grid-y'))]];
            }""")
            for left, top in tiles:
                self.assertEqual((left - grid[0]) % 48, 2)
                self.assertEqual((top - grid[1]) % 48, 2)
            if not editing:
                places.add((tuple(tiles[0]), tuple(grid)))
        self.assertEqual(len(places), 1, "The tiles and the grid moved when the shell changed")

    def test_the_preview_shows_the_whole_shell_centred(self):
        page = self.open(width=1920, height=1060)
        r = page.evaluate(RECTS)
        self.assertGreaterEqual(r["console"]["top"], r["bar"]["bottom"])
        self.assertLessEqual(r["edit"]["bottom"], 1060)
        # Centred in the room beside the settings, and between the top bar and the bottom.
        self.assertAlmostEqual(r["console"]["left"] - 16, r["panel"]["left"] - 16 - r["console"]["right"], delta=1)
        self.assertAlmostEqual(r["console"]["top"] - r["bar"]["bottom"], 1060 - r["edit"]["bottom"], delta=8)

    def test_layers_open_in_a_full_height_drawer_on_the_right(self):
        page = self.open(width=1920, height=1060)
        page.evaluate("setEditing(true)")
        page.click("#toggleLayers")
        page.evaluate(NEXT_PAINT)
        r = page.evaluate(RECTS)
        drawer = page.locator("#drawer").bounding_box()
        self.assertEqual((drawer["x"] + drawer["width"], drawer["y"], drawer["y"] + drawer["height"]),
                         (1920, r["bar"]["bottom"], 1060))
        self.assertLess(r["console"]["right"], drawer["x"])
        self.assertAlmostEqual(r["console"]["left"] - 16, drawer["x"] - 16 - r["console"]["right"], delta=1)
        page.click("#jsonTab")
        page.evaluate(NEXT_PAINT)
        self.assertEqual(page.evaluate(RECTS)["console"], r["console"], "Switching to JSON moved the screens")
        page.click("#layersTab")
        page.click("#toggleLayers")

    def test_clicking_a_screen_opens_the_editor_and_done_closes_it(self):
        page = self.open(width=1920, height=1060)
        preview = page.evaluate(RECTS)["top"]["width"]
        page.mouse.click(*self.ds_point(page, 128, 300))
        page.evaluate(NEXT_PAINT)
        r = page.evaluate(RECTS)
        self.assertTrue(page.evaluate("editing"))
        self.assertIsNone(page.evaluate("selectedId"), "The click that opens the editor shouldn't select anything")
        self.assertFalse(page.locator(".shell-art").is_visible())
        self.assertGreaterEqual(r["top"]["width"], 2 * W)
        done = page.locator("#doneButton").bounding_box()
        self.assertLess(done["x"] - r["screens"]["right"], 30, "Done isn't beside the screens")
        page.click("#doneButton")
        page.wait_for_function("document.querySelector('#shellArt svg')")
        self.assertFalse(page.evaluate("editing"))
        self.assertEqual(page.evaluate(RECTS)["top"]["width"], preview)
        page.mouse.click(*self.ds_point(page, 128, 300))
        page.keyboard.press("Escape")
        self.assertFalse(page.evaluate("editing"))

    def test_fill_uses_the_room_and_pixel_perfect_whole_pixels(self):
        page = self.open(width=1920, height=1060)
        for editing in (False, True):
            with self.subTest(editing=editing):
                page.evaluate("on => setEditing(on)", editing)
                page.click("#fitButton")
                r = page.evaluate(RECTS)
                under = (r["dock"] if editing else r["edit"])["height"] + 14
                room = 1060 - r["bar"]["height"] - under - 32
                filled = r["screens"]["height"] * 408 / 392 if editing else r["console"]["height"]
                self.assertAlmostEqual(filled, room, delta=1)
                page.click("#fitButton")
                width = page.evaluate(RECTS)["top"]["width"]
                self.assertEqual(width / W, round(width / W))
        self.reload(page)
        self.assertEqual(page.text_content("#fitButton"), "Pixel perfect")


def two_boxes():
    """Just two elements, at known places, so nothing else is in reach of a snap."""
    layout = harness.test_layout()
    keep = {e["id"]: e for e in layout["elements"]}
    cloud, other = keep["cloud"], next(e for e in layout["elements"] if e["id"] != "cloud" and e["type"] != "animation")
    cloud.update(x=100, y=120, w=40, h=36)
    other.update(x=20, y=20, w=50, h=30, hidden=False)
    layout["elements"] = [cloud, other]
    return layout, other["id"]


class EditingTests(BrowserCase):
    soft_reset = True
    editing = True

    def drag_cloud(self, page, dx, dy, alt=False):
        start = self.ds_point(page, 120, 138)
        end = self.ds_point(page, 120 + dx, 138 + dy)
        if alt:
            page.keyboard.down("Alt")
            self.addCleanup(page.keyboard.up, "Alt")
        self.drag(page, start, end)
        if alt:
            page.keyboard.up("Alt")
        return self.geometry(page, "cloud")

    def test_dragging_snaps_to_the_screen_edge(self):
        page = self.open(layout=two_boxes()[0])
        self.assertEqual(self.drag_cloud(page, -98, 0)[:2], (0, 120))

    def test_dragging_snaps_to_another_element(self):
        page = self.open(layout=two_boxes()[0])
        # Its left edge lands 2 short of the other element's right edge, at 70.
        self.assertEqual(self.drag_cloud(page, -32, 0)[:2], (70, 120))

    def test_alt_places_freely(self):
        page = self.open(layout=two_boxes()[0])
        self.assertEqual(self.drag_cloud(page, -98, 0, alt=True)[:2], (2, 120))

    def test_a_centre_half_a_pixel_away_is_no_snap_target(self):
        layout, other = two_boxes()
        next(e for e in layout["elements"] if e["id"] == other).update(x=20, y=60, w=51, h=30)   # Centre at 45.5
        page = self.open(layout=layout)
        # The cloud is 40 wide, so its centre can only be on a whole pixel: 46 isn't pulled to 45.5.
        self.assertEqual(self.drag_cloud(page, -74, 0)[0], 26)

    def test_typed_positions_are_whole_pixels(self):
        page = self.open(layout=two_boxes()[0])
        self.select(page, "cloud")
        box = page.locator("#fields .grid4 input").first
        box.fill("33.5")
        box.press("Tab")
        self.assertEqual(self.geometry(page, "cloud")[0], 34)

    def test_several_elements_move_align_copy_and_delete_together(self):
        layout, other = two_boxes()
        next(e for e in layout["elements"] if e["id"] == other)["locked"] = False
        page = self.open(layout=layout)
        self.select(page, "cloud")
        page.keyboard.down("Shift")
        page.mouse.click(*self.ds_point(page, 30, 30))
        page.keyboard.up("Shift")
        self.assertEqual(page.evaluate("selection().map(e => e.id).sort()"), sorted(["cloud", other]))
        self.assertEqual(page.locator(".box.selected").count(), 2)
        self.assertEqual(page.locator(".handle").count(), 0)
        self.assertEqual(page.text_content("#inspectorTitle"), "2 elements")

        page.keyboard.press("ArrowRight")
        self.assertEqual((self.geometry(page, "cloud")[0], self.geometry(page, other)[0]), (101, 21))
        page.keyboard.down("Alt")       # No snapping, so the distance is known
        self.drag(page, self.ds_point(page, 121, 150), self.ds_point(page, 131, 160))
        page.keyboard.up("Alt")
        self.assertEqual((self.geometry(page, "cloud")[:2], self.geometry(page, other)[:2]), ((111, 130), (31, 30)))
        page.click("[data-align=left]")
        self.assertEqual((self.geometry(page, "cloud")[0], self.geometry(page, other)[0]), (31, 31))
        page.keyboard.press("Control+z")
        self.assertEqual(self.geometry(page, "cloud")[0], 111)

        page.keyboard.press("Control+d")
        self.assertEqual(page.evaluate("layout.elements.length"), 4)
        self.assertEqual(page.evaluate("selection().length"), 2)
        self.assertEqual(sorted(page.evaluate("selection().map(e => [e.x, e.y])")), [[39, 38], [119, 138]])
        page.keyboard.press("Delete")
        self.assertEqual(page.evaluate("layout.elements.map(e => e.id).sort()"), sorted(["cloud", other]))

    def test_one_element_lines_up_with_its_screen(self):
        page = self.open(layout=two_boxes()[0])
        self.select(page, "cloud")
        page.click("[data-align=centre]")
        page.click("[data-align=bottom]")
        self.assertEqual(self.geometry(page, "cloud")[:2], (108, 156))

    def test_arrow_keys_nudge_the_selection(self):
        page = self.open(layout=two_boxes()[0])
        self.select(page, "cloud")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("Shift+ArrowDown")
        self.assertEqual(self.geometry(page, "cloud")[:2], (101, 128))


class TemplateTests(BrowserCase):
    soft_reset = True
    editing = True

    def test_a_swatch_setting_picks_its_value(self):
        layout = harness.test_layout()
        layout["elements"] = [{"id": "top_bar", "type": "top_bar", "x": 0, "y": 0, "w": 256, "h": 16, "props": {}}]
        page = self.open(layout=layout)
        self.select(page, "top_bar")
        swatches = page.locator("#fields .shell-swatch")
        self.assertEqual(swatches.count(), 17)
        self.assertEqual(swatches.first.get_attribute("aria-pressed"), "true")   # Follows the theme
        swatches.nth(3).click()
        self.assertEqual(self.element(page, "top_bar")["props"]["colour"], "2")
        self.assertEqual(page.locator("#fields .shell-swatch").nth(3).get_attribute("aria-pressed"), "true")


class SeamAnimationTests(BrowserCase):
    soft_reset = True
    editing = True

    def painted(self, page) -> tuple:
        """Which DS rows show the animation's colour, on each LCD."""
        page.wait_for_function("[...document.querySelectorAll('.anim-view img')].every(i => i.complete && i.style.width)")
        page.evaluate(NEXT_PAINT)
        shot = screens_shot(page)
        pixels = shot.shape[1] // W
        rows = shot[::pixels, ::pixels].astype(int)
        red = (rows[..., 0] > 200) & (rows[..., 1] < 60) & (rows[..., 2] < 60)
        hit = np.nonzero(red.any(axis=1))[0]
        hinge = page.evaluate("HINGE")
        return [int(r) for r in hit if r < SEAM], [int(r) for r in hit if SEAM <= r < SEAM + hinge], \
               [int(r) - hinge for r in hit if r >= SEAM + hinge]

    def open_at(self, y, h=36, **options):
        layout = changed(lambda e: e["cloud"].update(x=100, y=y, w=40, h=h))
        page = self.open(layout=layout, frame=black_frame(), **options)
        hide_chrome(page)
        return page

    def views(self, page):
        return page.evaluate("[...document.querySelectorAll('.animations')].map(a => a.children.length)")

    def test_animation_over_the_seam_shows_on_both_lcds(self):
        page = self.open_at(180)
        self.assertEqual(self.views(page), [1, 1])
        top, hinge, bottom = self.painted(page)
        self.assertEqual(top, list(range(180, 192)))
        self.assertEqual(hinge, [])
        self.assertEqual(bottom, list(range(192, 216)))

    def test_it_works_at_two_device_pixels_per_ds_pixel(self):
        page = self.open_at(180, width=1920, height=1060)
        top, hinge, bottom = self.painted(page)
        self.assertEqual((top[0], top[-1], hinge, bottom[0], bottom[-1]), (180, 191, [], 192, 215))

    def test_animation_on_one_screen_stays_there(self):
        self.assertEqual(self.views(self.open_at(100)), [1, 0])
        self.assertEqual(self.views(self.open_at(250)), [0, 1])

    def test_animation_touching_the_seam_is_not_on_the_other_lcd(self):
        self.assertEqual(self.views(self.open_at(156)), [1, 0])
        self.assertEqual(self.views(self.open_at(192)), [0, 1])

    def test_dragging_onto_the_seam_shows_it_on_both_lcds_at_once(self):
        page = self.open_at(100)
        start = self.ds_point(page, 120, 118)
        end = self.ds_point(page, 120, 188)
        self.press(page, start)
        page.mouse.move(*end, steps=3)
        self.assertEqual(self.views(page), [1, 1])
        page.mouse.up()
        self.assertEqual(self.geometry(page, "cloud")[1], 170)
