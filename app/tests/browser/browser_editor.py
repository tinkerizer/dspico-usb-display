"""Editing on the preview: dragging, resizing, history, and the layers tree."""
from harness import SEAM, BrowserCase, changed


class DragTests(BrowserCase):
    soft_reset = True
    editing = True

    def drag(self, page, start, end):
        # These check exact movement, so they hold Alt to place freely instead of snapping.
        page.keyboard.down("Alt")
        try:
            super().drag(page, start, end)
        finally:
            page.keyboard.up("Alt")

    def centre(self, page, id_):
        x, y, w, h = self.geometry(page, id_)
        return x + w // 2, y + h // 2

    def check_one_to_one(self, **options):
        page = self.open(**options)
        cx, cy = self.centre(page, "clock")
        self.drag(page, self.ds_point(page, cx, cy), self.ds_point(page, cx + 23, cy + 17))
        self.assertEqual(self.geometry(page, "clock"), (15 + 23, 31 + 17, 97, 97))

    def test_drag_is_one_to_one_at_one_pixel_per_ds_pixel(self):
        self.check_one_to_one()

    def test_drag_is_one_to_one_at_two_pixels_per_ds_pixel(self):
        self.check_one_to_one(width=1920, height=1060)

    def test_drag_is_one_to_one_at_dpr_2(self):
        self.check_one_to_one(dpr=2)

    def test_resize_is_one_to_one(self):
        page = self.open()
        self.select(page, "clock")
        self.drag(page, self.ds_point(page, 112, 128), self.ds_point(page, 132, 118))
        self.assertEqual(self.geometry(page, "clock"), (15, 31, 117, 87))

    def test_resize_from_the_top_left_keeps_the_far_corner(self):
        page = self.open()
        self.select(page, "clock")
        self.drag(page, self.ds_point(page, 15, 31), self.ds_point(page, 25, 41))
        self.assertEqual(self.geometry(page, "clock"), (25, 41, 87, 87))

    def test_drag_across_the_hinge_skips_its_rows(self):
        page = self.open()
        cx, cy = self.centre(page, "clock")
        # 200 rows down the preview, of which those in the hinge don't exist on the DS.
        self.drag(page, self.view_point(page, cx, cy + 40), self.view_point(page, cx, cy + 240))
        self.assertEqual(self.geometry(page, "clock")[1], 31 + 200 - page.evaluate("HINGE"))

    def test_drag_back_up_across_the_hinge(self):
        page = self.open()
        cx = self.centre(page, "cpu_graph")[0]
        self.drag(page, self.view_point(page, cx, 290 + page.evaluate("HINGE")), self.view_point(page, cx, 90))
        self.assertEqual(self.geometry(page, "cpu_graph")[1], 281 - 200)

    def test_box_follows_the_drag_onto_the_bottom_screen(self):
        page = self.open()
        self.drag(page, self.ds_point(page, 60, 80), self.ds_point(page, 60, 300))
        y = self.geometry(page, "clock")[1]
        box = page.evaluate("document.querySelector('#overlay [data-id=clock]').getBoundingClientRect().top")
        self.assertAlmostEqual(box, self.ds_point(page, 0, y)[1], delta=0.5)

    def test_resize_across_the_hinge_skips_its_rows(self):
        page = self.open()
        self.select(page, "clock")
        self.drag(page, self.ds_point(page, 112, 128), self.ds_point(page, 112, 228))
        self.assertEqual(self.geometry(page, "clock")[3], 197)

    def test_pointer_in_the_hinge_stops_at_the_seam(self):
        page = self.open()
        self.press(page, self.view_point(page, 60, 80))
        hinge = page.evaluate("HINGE")
        for row in (SEAM + 1, SEAM + hinge // 2, SEAM + hinge - 1):
            page.mouse.move(*self.view_point(page, 60, row))
            self.assertEqual(self.geometry(page, "clock")[1], 31 + SEAM - 80, f"Pointer at row {row}")
        page.mouse.up()

    def test_undo_and_redo_a_drag(self):
        page = self.open()
        self.drag(page, self.ds_point(page, 60, 80), self.ds_point(page, 70, 90))
        moved = self.geometry(page, "clock")
        self.assertEqual(moved[:2], (25, 41))

        page.click("#undo")
        self.assertEqual(self.geometry(page, "clock")[:2], (15, 31))
        self.wait_saved(page, lambda e: e["clock"]["x"] == 15)
        page.click("#redo")
        self.assertEqual(self.geometry(page, "clock"), moved)
        self.wait_saved(page, lambda e: e["clock"]["x"] == 25)

    def test_undo_and_redo_keys(self):
        page = self.open()
        self.drag(page, self.ds_point(page, 60, 80), self.ds_point(page, 70, 90))
        page.keyboard.press("Control+z")
        self.assertEqual(self.geometry(page, "clock")[:2], (15, 31))
        page.keyboard.press("Control+Shift+z")
        self.assertEqual(self.geometry(page, "clock")[:2], (25, 41))

    def test_one_drag_is_one_undo_step(self):
        page = self.open()
        self.drag(page, self.ds_point(page, 60, 80), self.ds_point(page, 70, 90))
        self.assertEqual(page.evaluate("undoStack.length"), 1)

    def test_a_click_is_not_a_drag(self):
        page = self.open()
        point = self.ds_point(page, 60, 80)
        page.mouse.click(*point)
        self.assertEqual(page.evaluate("selectedId"), "clock")
        self.assertEqual(page.evaluate("undoStack.length"), 0)

    def test_arrows_nudge(self):
        page = self.open()
        self.select(page, "clock")
        for key in ("ArrowRight", "ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "ArrowUp"):
            page.keyboard.press(key)
        self.assertEqual(self.geometry(page, "clock")[:2], (16, 30))
        page.keyboard.press("Shift+ArrowRight")
        self.assertEqual(self.geometry(page, "clock")[:2], (24, 30))
        self.wait_saved(page, lambda e: e["clock"]["x"] == 24)
        page.keyboard.press("Control+z")
        self.assertEqual(self.geometry(page, "clock")[:2], (16, 30))

    def test_arrows_leave_a_locked_element_alone(self):
        page = self.open()
        self.select(page, "top_paper")
        page.keyboard.press("ArrowRight")
        self.assertEqual(self.geometry(page, "top_paper")[:2], (0, 0))

    def test_add_and_delete(self):
        page = self.open()
        before = page.evaluate("layout.elements.length")
        page.click("#addButton")
        page.click("#addGrid button[data-type=panel]")
        self.assertEqual(page.evaluate("selectedId"), "panel_1")
        self.assertEqual(page.evaluate("layout.elements.length"), before + 1)
        self.assertEqual(page.locator("#overlay [data-id=panel_1]").count(), 1)
        self.wait_saved(page, lambda e: "panel_1" in e)

        page.keyboard.press("Delete")
        self.assertEqual(page.evaluate("selectedId"), None)
        self.assertEqual(page.locator("#overlay [data-id=panel_1]").count(), 0)
        self.wait_saved(page, lambda e: "panel_1" not in e)

        page.keyboard.press("Control+z")
        self.assertEqual(page.locator("#overlay [data-id=panel_1]").count(), 1)
        self.wait_saved(page, lambda e: "panel_1" in e)

    def test_delete_button(self):
        page = self.open()
        self.select(page, "clock")
        page.click("#fields button:has-text('Delete')")
        self.assertEqual(self.element(page, "clock"), None)
        self.assertTrue(page.locator("#inspector").is_hidden())

    def test_a_new_element_gets_a_free_id(self):
        page = self.open()
        for wanted in ("text_1", "text_2"):
            page.click("#addButton")
            page.click("#addGrid button[data-type=text]")
            self.assertEqual(page.evaluate("selectedId"), wanted)

    def test_a_saved_drag_survives_a_reload(self):
        page = self.open()
        self.drag(page, self.ds_point(page, 60, 80), self.ds_point(page, 70, 90))
        self.wait_saved(page, lambda e: e["clock"]["x"] == 25 and e["clock"]["y"] == 41)
        self.reload(page)
        self.assertEqual(self.geometry(page, "clock")[:2], (25, 41))


class LayerTests(BrowserCase):
    soft_reset = True
    editing = True

    def rows(self, page) -> dict:
        return page.evaluate("""Object.fromEntries([...document.querySelectorAll('#list .item')]
          .map(row => [row.dataset.id, Number(row.style.getPropertyValue('--depth'))]))""")

    def open_layers(self, **options):
        page = self.open(**options)
        page.evaluate("""localStorage.setItem('drawer', 'layers');
          if (document.getElementById('drawer').hidden) showDrawer('layers');""")
        return page

    def twisty(self, page, id_):
        return page.locator(f"#list .item[data-id={id_}] button.twisty")

    def test_nesting_comes_from_geometry(self):
        rows = self.rows(self.open_layers())
        self.assertEqual(rows["top_paper"], 0)
        self.assertEqual(rows["bottom_paper"], 0)
        self.assertEqual(rows["clock"], 1)
        self.assertEqual(rows["card"], 1)
        self.assertEqual(rows["card_gpu"], 2)
        self.assertEqual(rows["cloud"], 2)

    def test_front_most_comes_first(self):
        ids = list(self.rows(self.open_layers()))
        self.assertLess(ids.index("bottom_paper"), ids.index("top_paper"))
        self.assertLess(ids.index("card_net"), ids.index("card_gpu"))

    def test_nudging_out_of_a_parent_moves_it_in_the_tree(self):
        layout = changed(lambda e: e["cloud"].update(x=33, y=217))
        page = self.open_layers(layout=layout)
        self.assertEqual(self.rows(page)["cloud"], 2)
        self.select(page, "cloud")
        page.keyboard.press("ArrowLeft")
        self.assertEqual(self.rows(page)["cloud"], 1)

    def test_dragging_out_of_a_parent_moves_it_in_the_tree(self):
        page = self.open_layers()
        self.assertEqual(self.rows(page)["card_gpu"], 2)
        self.drag(page, self.ds_point(page, 120, 228), self.ds_point(page, 120, 208))
        self.assertEqual(self.rows(page)["card_gpu"], 1)

    def test_collapse_hides_the_branch_and_survives_a_reload(self):
        page = self.open_layers()
        self.twisty(page, "card").click()
        rows = self.rows(page)
        self.assertIn("card", rows)
        self.assertNotIn("card_gpu", rows)

        self.reload(page)
        rows = self.rows(page)
        self.assertIn("card", rows)
        self.assertNotIn("card_gpu", rows)
        self.assertEqual(self.twisty(page, "card").get_attribute("aria-expanded"), "false")

        self.twisty(page, "card").click()
        self.assertIn("card_gpu", self.rows(page))
        self.reload(page)
        self.assertIn("card_gpu", self.rows(page))

    def test_collapsing_does_not_select(self):
        page = self.open_layers()
        self.twisty(page, "card").click()
        self.assertEqual(page.evaluate("selectedId"), None)

    def test_selecting_in_the_preview_opens_the_branch(self):
        page = self.open_layers()
        self.twisty(page, "bottom_paper").click()
        self.assertNotIn("card", self.rows(page))

        page.mouse.click(*self.ds_point(page, 221, 240))
        self.assertEqual(page.evaluate("selectedId"), "card")
        self.assertIn("card", self.rows(page))
        self.reload(page)
        self.assertIn("card", self.rows(page))

    def test_selecting_a_deep_child_opens_every_level(self):
        page = self.open_layers()
        self.twisty(page, "card").click()
        self.twisty(page, "bottom_paper").click()
        page.mouse.click(*self.ds_point(page, 120, 228))
        self.assertEqual(page.evaluate("selectedId"), "card_gpu")
        self.assertEqual(self.rows(page)["card_gpu"], 2)

    def test_a_row_selects_its_element(self):
        page = self.open_layers()
        page.click("#list .item[data-id=clock]")
        self.assertEqual(page.locator("#overlay .box.selected").get_attribute("data-id"), "clock")
