"""The crop tool, on art made by the harness: 64x48, with pixels 4 wide."""
from harness import SCALE, BrowserCase, changed, image_element, test_layout

NATURAL_W, NATURAL_H = 64, 48
CROPPER_READY = """() => document.querySelectorAll('.crop-handle').length === 4
  && [...document.querySelectorAll('.chips button')].some(b => b.textContent === '1×')"""


class CropCase(BrowserCase):
    soft_reset = True
    editing = True

    def open_crop(self, crop=None, **props):
        def update(elements):
            elements["art"]["props"].update(props)
            if crop:
                elements["art"]["props"].update(zip(("crop_x", "crop_y", "crop_w", "crop_h"), crop))
                elements["art"].update(w=crop[2], h=crop[3])
        page = self.open(layout=changed(update), height=900)
        self.select(page, "art")
        self.ready(page)
        return page

    def ready(self, page):
        page.wait_for_function(CROPPER_READY)
        page.locator(".cropper").scroll_into_view_if_needed()

    def crop(self, page) -> tuple:
        props = self.element(page, "art")["props"]
        return props["crop_x"], props["crop_y"], props["crop_w"], props["crop_h"]

    def point(self, page, x, y) -> tuple:
        """A source pixel's position in the cropper."""
        left, top, width, height = page.evaluate(
            "(({left, top, width, height}) => [left, top, width, height])"
            "(document.querySelector('.cropper').getBoundingClientRect())")
        return left + x / NATURAL_W * width, top + y / NATURAL_H * height

    def drag_crop(self, page, start, end):
        self.drag(page, self.point(page, *start), self.point(page, *end))
        self.ready(page)

    def corner(self, page, name) -> tuple:
        rect = page.evaluate("""name => {
          const { left, top, width, height } = document.querySelector(`.crop-handle.${name}`).getBoundingClientRect();
          return [left + width / 2, top + height / 2];
        }""", name)
        return tuple(rect)


class CropTests(CropCase):
    def test_drawing_on_a_full_crop(self):
        page = self.open_crop()
        self.drag_crop(page, (16, 12), (48, 36))
        self.assertEqual(self.crop(page), (16, 12, 32, 24))

    def test_drawing_backwards(self):
        page = self.open_crop()
        self.drag_crop(page, (48, 36), (16, 12))
        self.assertEqual(self.crop(page), (16, 12, 32, 24))

    def test_drawing_saves_and_undoes(self):
        page = self.open_crop()
        self.drag_crop(page, (16, 12), (48, 36))
        self.wait_saved(page, lambda e: e["art"]["props"]["crop_w"] == 32)
        page.locator("#inspectorTitle").click()
        page.keyboard.press("Control+z")
        self.assertEqual(self.crop(page), (0, 0, 0, 0))

    def test_box_follows_the_crop_shape(self):
        page = self.open_crop()
        self.drag_crop(page, (16, 16), (48, 24))
        x, y, w, h = self.geometry(page, "art")
        self.assertEqual((w, h), (64, 16))

    def test_moving_a_crop(self):
        page = self.open_crop(crop=(16, 12, 32, 24))
        self.drag_crop(page, (32, 24), (40, 28))
        self.assertEqual(self.crop(page), (24, 16, 32, 24))

    def test_a_moved_crop_stays_inside_the_image(self):
        page = self.open_crop(crop=(16, 12, 32, 24))
        self.drag_crop(page, (32, 24), (63, 47))
        self.assertEqual(self.crop(page), (32, 24, 32, 24))

    def test_corner_handles(self):
        cases = {
            "se": ((40, 30), (16, 12, 24, 18)),
            "nw": ((24, 20), (24, 20, 24, 16)),
            "ne": ((40, 20), (16, 20, 24, 16)),
            "sw": ((24, 30), (24, 12, 24, 18)),
        }
        for name, (target, wanted) in cases.items():
            with self.subTest(corner=name):
                page = self.open_crop(crop=(16, 12, 32, 24))
                self.drag(page, self.corner(page, name), self.point(page, *target))
                self.ready(page)
                self.assertEqual(self.crop(page), wanted)

    def test_stray_clicks_do_nothing(self):
        for name, crop, spot in (("inside a crop", (16, 12, 32, 24), (32, 24)),
                                 ("outside a crop", (16, 12, 32, 24), (4, 4)),
                                 ("on a full crop", None, (32, 24))):
            with self.subTest(name):
                page = self.open_crop(crop=crop)
                before = self.crop(page), self.geometry(page, "art")
                page.mouse.click(*self.point(page, *spot))
                self.assertEqual((self.crop(page), self.geometry(page, "art")), before)
                self.assertEqual(page.evaluate("undoStack.length"), 0)

    def test_full_image_button(self):
        page = self.open_crop(crop=(16, 12, 32, 24))
        page.click(".chips button:has-text('Full image')")
        self.ready(page)
        self.assertEqual(self.crop(page), (0, 0, NATURAL_W, NATURAL_H))
        self.assertEqual(page.locator(".crop-area").evaluate("a => a.style.width"), "100%")


class PixelLockTests(CropCase):
    def assert_whole(self, page):
        x, y, w, h = self.crop(page)
        for value in (x, y, w, h):
            self.assertEqual(value % SCALE, 0, f"Crop {x, y, w, h} isn't on art pixels")
        _, _, box_w, box_h = self.geometry(page, "art")
        self.assertEqual(box_w * SCALE % w, 0, "Art pixels aren't a whole size across")
        self.assertEqual(box_h * SCALE % h, 0, "Art pixels aren't a whole size down")
        self.assertEqual(box_w * SCALE // w, box_h * SCALE // h, "Art pixels aren't square")

    def test_drawing_lands_on_art_pixels(self):
        page = self.open_crop(pixel_lock="yes")
        self.drag_crop(page, (5, 7), (37, 30))
        self.assertEqual(self.crop(page), (4, 8, 32, 24))
        self.assert_whole(page)

    def test_what_stays_in_the_crop_stays_put(self):
        page = self.open_crop(pixel_lock="yes")
        self.drag_crop(page, (5, 7), (37, 30))
        self.assertEqual(self.geometry(page, "art"), (150 + 4, 200 + 8, 32, 24))

    def test_moving_lands_on_art_pixels(self):
        page = self.open_crop(crop=(16, 12, 32, 24), pixel_lock="yes")
        self.drag_crop(page, (32, 24), (37, 27))
        self.assertEqual(self.crop(page), (20, 16, 32, 24))
        self.assert_whole(page)

    def test_a_corner_lands_on_art_pixels(self):
        page = self.open_crop(crop=(16, 12, 32, 24), pixel_lock="yes")
        self.drag(page, self.corner(page, "se"), self.point(page, 39, 29))
        self.ready(page)
        self.assertEqual(self.crop(page), (16, 12, 24, 16))
        self.assert_whole(page)

    def test_full_image_keeps_the_pixel_size(self):
        page = self.open_crop(crop=(16, 12, 32, 24), pixel_lock="yes")
        page.click(".chips button:has-text('Full image')")
        self.ready(page)
        self.assertEqual(self.crop(page), (0, 0, NATURAL_W, NATURAL_H))
        self.assertEqual(self.geometry(page, "art")[2:], (64, 48))
        self.assert_whole(page)

    def test_resizing_keeps_whole_pixels(self):
        page = self.open_crop(pixel_lock="yes")
        # 16 art pixels across, so the box comes in steps of 16.
        x, y, w, h = self.geometry(page, "art")
        self.drag(page, self.ds_point(page, x + w, y + h), self.ds_point(page, x + w + 21, y + h + 15))
        self.assertEqual(self.geometry(page, "art")[2:], (80, 60))

    def test_turning_the_lock_on_snaps_straight_away(self):
        layout = test_layout()
        layout["elements"][-1] = image_element("art", 150, 200, 70, 50)
        page = self.open(layout=layout, height=900)
        self.select(page, "art")
        self.ready(page)
        page.locator("label.switch:has-text('Lock to pixel scale')").click()
        page.wait_for_function("(({w, h}) => w === 64 && h === 48)(layout.elements.find(e => e.id === 'art'))")
