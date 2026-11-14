"""Tests for the codec, device session and dashboard. Hardware is not needed."""
import http.client
import json
import shutil
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dsdash import codec, device, elements, firmware, gpu, installer, layout, templates, themes, updates, widgets
from dsdash.sensors import Stats


def rle_decode(data: bytes) -> list:
    tokens = struct.unpack(f"<{len(data) // 2}H", data)
    out, index = [], 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        count = (token & 0x7FFF) + 1
        if token & 0x8000:
            out += [tokens[index]] * count
            index += 1
        else:
            out += tokens[index:index + count]
            index += count
    return out


class CodecTests(unittest.TestCase):
    def test_rle_round_trips(self):
        rng = np.random.default_rng(1)
        cases = [
            np.array([5], np.uint16),
            np.full(70000, 7, np.uint16),
            rng.integers(0, 65535, 5000, dtype=np.uint16),
            np.repeat(rng.integers(0, 9, 800, dtype=np.uint16), rng.integers(1, 6, 800)),
        ]
        for pixels in cases:
            self.assertEqual(rle_decode(codec.rle_encode(pixels)), pixels.tolist())

    def test_no_change_means_no_rects(self):
        frame = np.zeros((384, 256), np.uint16)
        self.assertEqual(codec.changed_rects(frame, frame.copy()), [])

    def test_separate_changes_stay_separate(self):
        old = np.zeros((384, 256), np.uint16)
        new = old.copy()
        new[10:12, 20:30] = 1
        new[300:302, 200:210] = 1
        self.assertEqual(sorted(codec.changed_rects(old, new)), [(20, 10, 10, 2), (200, 300, 10, 2)])

    def test_rects_cover_every_change(self):
        rng = np.random.default_rng(2)
        old = np.zeros((384, 256), np.uint16)
        new = old.copy()
        for _ in range(40):
            x, y = rng.integers(0, 250), rng.integers(0, 380)
            new[y:y + 3, x:x + 5] = 1
        patched = old.copy()
        for x, y, width, height in codec.changed_rects(old, new):
            patched[y:y + height, x:x + width] = new[y:y + height, x:x + width]
        self.assertTrue((patched == new).all())


class AnimationTests(unittest.TestCase):
    def make_gif(self, folder):
        path = Path(folder) / "two.gif"
        left = Image.new("RGB", (20, 10), "#ff0000")
        left.paste(Image.new("RGB", (10, 10), "#0000ff"), (10, 0))
        right = left.transpose(Image.FLIP_LEFT_RIGHT)
        left.save(path, save_all=True, append_images=[right], duration=[100, 100], loop=0)
        return path

    def test_clips_what_hangs_off_the_screen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_gif(folder)
            area, frames = codec.encode_animation(str(path), (-3, 380, 8, 8))
        self.assertEqual(struct.unpack("<4H", frames[0][1][:8]), (0, 380, 5, 4))

    def test_trims_transparent_margins(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "dot.gif"
            picture = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
            picture.paste((255, 0, 0, 255), (5, 6, 10, 12))
            picture.save(path, transparency=0, disposal=2)
            area, frames = codec.encode_animation(str(path), (100, 50, 20, 20))
        self.assertEqual(area, (105, 56, 5, 6))
        self.assertEqual(struct.unpack("<4H", frames[0][1][:8]), (105, 56, 5, 6))

    def test_transparent_pixels_show_what_is_under_them(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ring.gif"
            picture = Image.new("RGBA", (6, 6), (0, 0, 0, 0))
            picture.paste((255, 0, 0, 255), (0, 0, 6, 1))
            picture.paste((255, 0, 0, 255), (0, 5, 6, 6))
            picture.save(path, transparency=0, disposal=2)
            area, frames = codec.encode_animation(str(path), (0, 0, 6, 6))
        pixels = np.array(rle_decode(frames[0][1][8:]), dtype=np.uint16).reshape(6, 6)
        self.assertTrue((pixels[[0, 5]] == 0x801F).all())
        self.assertTrue((pixels[1:5] == codec.TRANSPARENT).all())

    def test_refuses_an_animation_fully_off_the_screen(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_gif(folder)
            with self.assertRaises(ValueError):
                codec.encode_animation(str(path), (-20, 0, 8, 8))

    def test_sleep_screen_is_cropped_to_its_drawing_and_centred(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cat.gif"
            frames = [Image.new("RGB", (400, 300), "#000000") for _ in range(2)]
            frames[0].paste((255, 200, 0), (100, 50, 110, 60))
            frames[1].paste((255, 200, 0), (120, 70, 130, 80))
            frames[0].save(path, save_all=True, append_images=frames[1:], duration=500, loop=0)
            self.assertEqual(codec.drawing_box(str(path)), (100, 50, 30, 30))
            area, frames = codec.encode_sleep(str(path), "bottom")
        self.assertEqual(area, (113, 192 + 81, 30, 30))

    def test_crop_selects_part_of_the_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.make_gif(folder)
            area, frames = codec.encode_animation(str(path), (0, 0, 8, 8), (0, 0, 10, 10))

        body = frames[0][1]
        pixels = rle_decode(body[8:])
        self.assertEqual(struct.unpack("<4H", body[:8]), (0, 0, 8, 8))
        self.assertEqual(len(pixels), 64)
        self.assertEqual(len(set(pixels)), 1)   # Only the red half


class FakePort:
    def __init__(self, on_write=None):
        self.written = []
        self.is_open = True
        self.on_write = on_write

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.is_open = False

    def reset_input_buffer(self):
        pass

    def readline(self):
        return b"ds_256x384.v2\n"

    def write(self, data):
        self.written.append(data)
        if self.on_write:
            self.on_write(data)


def packets_in(data: bytes) -> list:
    out, position = [], 0
    while position < len(data):
        magic, kind, _, length = struct.unpack_from("<BBHI", data, position)
        assert magic == device.MAGIC
        out.append(kind)
        position += 8 + ((length + 3) & ~3)
    return out


class DeviceTests(unittest.TestCase):
    def test_port_selection_skips_dev_port(self):
        def port(name, location):
            return SimpleNamespace(device=name, location=location, vid=device.USB_VID, pid=device.USB_PID)

        self.assertEqual(device.find_display_port([port("COM4", "1-1:x.2"), port("COM3", None)]), "COM3")
        self.assertEqual(device.find_display_port([port("COM4", "1-1:x.2")]), None)

    def test_packets_are_word_aligned(self):
        self.assertEqual(len(device.packet(1, b"abc")) % 4, 0)

    def test_unchanged_frames_send_nothing_and_animations_hide_nothing(self):
        ds = device.DsDevice()
        frame = np.full((384, 256), codec.BLACK, np.uint16)
        self.assertEqual(ds._frame_packets(frame), b"")

        # The DS keeps live pixels under an animation, to show through its transparent ones.
        ds._animations = [device.Animation((10, 10, 20, 20), [])]
        frame[12, 12] = 0xFFFF
        self.assertEqual(packets_in(ds._frame_packets(frame)), [device.PACKET_RECT_RAW])

    def test_session_handshakes_then_sends_frame(self):
        ds = device.DsDevice()
        port = FakePort(on_write=lambda data: ds.stop() if len(port.written) >= 2 else None)
        frame = np.full((384, 256), codec.BLACK, np.uint16)
        frame[0:4, 0:4] = 0xFFFF
        ds.submit_frame(frame)
        ds._session(port, "COM3")
        self.assertEqual(packets_in(port.written[0]), [device.PACKET_HELLO])
        kinds = packets_in(port.written[1])
        self.assertIn(device.PACKET_BRIGHTNESS, kinds)
        self.assertIn(device.PACKET_RECT_RLE, kinds)
        self.assertIn(device.PACKET_ANIM_RESET, kinds)
        self.assertTrue(ds.status.connected)

    def test_the_sleep_screen_loads_into_its_own_slot_without_playing(self):
        ds = device.DsDevice()
        layout_gif = device.Animation((0, 0, 4, 4), [(1, b"a" * 12)])
        sleep_gif = device.Animation((0, 0, 4, 4), [(1, b"b" * 12)])
        packets = packets_in(ds._animation_packets([layout_gif], (sleep_gif, 30)))
        self.assertEqual(packets, [device.PACKET_ANIM_BEGIN, device.PACKET_ANIM_FRAME, device.PACKET_ANIM_PLAY,
                                   device.PACKET_ANIM_BEGIN, device.PACKET_ANIM_FRAME, device.PACKET_ANIM_SLEEP])

    def test_a_long_pause_starts_a_new_session(self):
        # Waking from sleep: the port may still work, but the DS can have reset or missed data.
        ds = device.DsDevice()
        port = FakePort()
        with mock.patch.object(device, "PAUSE_SECONDS", -1):
            with self.assertRaises(device.Paused):
                ds._session(port, "COM3")
        self.assertEqual(packets_in(port.written[0]), [device.PACKET_HELLO])

    def test_a_quiet_session_still_sends_keepalives(self):
        # The DS goes dark when nothing arrives for a while, as when the PC sleeps.
        ds = device.DsDevice()
        port = FakePort(on_write=lambda data: ds.stop() if len(port.written) >= 3 else None)
        with mock.patch.object(device, "KEEPALIVE_SECONDS", 0):
            ds._session(port, "COM3")
        self.assertEqual(packets_in(port.written[2]), [device.PACKET_KEEPALIVE])


class LayoutTests(unittest.TestCase):
    def test_default_layout_is_valid(self):
        self.assertTrue(layout.validate(layout.default_layout())["elements"])

    def test_unknown_type_and_duplicate_ids_are_rejected(self):
        with self.assertRaises(layout.LayoutError):
            layout.validate({"elements": [{"id": "a", "type": "nope", "x": 0, "y": 0, "w": 1, "h": 1}]})
        element = {"id": "a", "type": "panel", "x": 0, "y": 0, "w": 1, "h": 1}
        with self.assertRaises(layout.LayoutError):
            layout.validate({"elements": [element, dict(element)]})

    def test_malformed_input_is_a_layout_error(self):
        for bad in ({}, {"elements": 5}, {"elements": [5]}, {"elements": [{"id": "a"}]}):
            with self.assertRaises((layout.LayoutError, ValueError)):
                layout.validate(bad)

    def test_file_references_cannot_escape(self):
        for bad in ("art:../../../dsdash/app.py", "local:../layout.png", "art:/etc/passwd.png", "c:/x.png", "art:"):
            with self.assertRaises(layout.LayoutError):
                layout.resolve_file(bad)

    def test_upload_names_are_flattened(self):
        self.assertEqual(layout.safe_upload_name("../../evil cat.gif"), "evil_cat.gif")
        with self.assertRaises(layout.LayoutError):
            layout.safe_upload_name("run.py")

    def test_missing_props_get_defaults_and_bad_colors_fail(self):
        element = {"id": "a", "type": "panel", "x": 0, "y": 0, "w": 9, "h": 9}
        self.assertEqual(layout.validate({"elements": [element]})["elements"][0]["props"]["fill"], "#fbfbfb")
        element["props"] = {"fill": "red; x"}
        with self.assertRaises(layout.LayoutError):
            layout.validate({"elements": [element]})


class AlignmentTests(unittest.TestCase):
    def test_boxes_sit_evenly_between_the_grid_lines(self):
        """The bottom screen's grid has lines at 31, 79, 127, 175 and 223, and boxes keep a pixel clear of them."""
        boxes = {e["id"]: e for e in layout.default_layout()["elements"] if e["type"] == "button"}
        for box in boxes.values():
            self.assertIn(box["x"], (33, 129))
            self.assertIn(box["x"] + box["w"], (126, 222))

    def test_old_layouts_get_the_default_boxes_put_right(self):
        old = layout.default_layout()
        old["version"] = 1
        for element in old["elements"]:
            if element["id"] == "card":
                element["w"] = 190
            if element["id"] == "disk_bar":
                element.update(x=50, w=174)      # Moved by the user, so left alone
        new = {e["id"]: e for e in layout.from_saved(old)["elements"]}
        self.assertEqual(new["card"]["w"], 189)
        self.assertEqual((new["disk_bar"]["x"], new["disk_bar"]["w"]), (50, 174))


class TemplateTests(unittest.TestCase):
    def bar(self, **props):
        element = layout.validate({"elements": [{"id": "top_bar", "type": "top_bar", "x": 0, "y": 0, "w": 256, "h": 16,
                                                  "props": props}]})
        return themes.apply_layout(element, {**themes.BUILT_IN["Classic"], "bar": 5})["elements"]

    def test_top_bar_is_an_element_type(self):
        self.assertTrue(layout.SCHEMA["top_bar"]["template"])
        self.assertEqual(layout.default_layout()["elements"][1]["type"], "top_bar")

    def test_expands_into_its_pieces_following_the_theme_colour(self):
        pieces = self.bar()
        self.assertEqual([p["id"] for p in pieces], ["top_bar.bar", "top_bar.name", "top_bar.time", "top_bar.date",
                                                    "top_bar.usb", "top_bar.battery"])
        self.assertEqual(pieces[0]["props"]["file"], "art:topbar/5.png")
        self.assertEqual(pieces[1]["props"]["text"], "{host}")

    def test_a_chosen_colour_stays_whatever_the_theme(self):
        self.assertEqual(self.bar(colour="2")[0]["props"]["file"], "art:topbar/2.png")

    def test_settings_switch_pieces_off(self):
        ids = [p["id"] for p in self.bar(show_time="no", show_battery="no")]
        self.assertNotIn("top_bar.time", ids)
        self.assertNotIn("top_bar.battery", ids)

    def test_old_top_bar_pieces_become_one_element(self):
        old = {"elements": [
            {"id": "top_bar", "type": "image", "x": 0, "y": 0, "w": 256, "h": 16, "props": {"file": "art:topbar/11.png"}},
            {"id": "bar_name", "type": "text", "x": 3, "y": 2, "w": 138, "h": 12, "props": {"text": "me", "color": "#ffff00"}},
            {"id": "bar_time", "type": "text", "x": 144, "y": 2, "w": 30, "h": 12, "hidden": True, "props": {}},
            {"id": "clock", "type": "clock", "x": 15, "y": 31, "w": 97, "h": 97, "props": {}},
        ]}
        new = layout.validate(layout.upgrade_top_bar(old))["elements"]
        self.assertEqual([e["id"] for e in new], ["top_bar", "clock"])
        self.assertEqual(new[0]["type"], "top_bar")
        self.assertEqual((new[0]["props"]["name"], new[0]["props"]["text_colour"]), ("me", "#ffff00"))
        self.assertEqual((new[0]["props"]["show_time"], new[0]["props"]["show_date"]), ("no", "no"))

    def test_draws_the_same_as_the_old_pieces(self):
        old = {"elements": [layout._element(*args, **props) for args, props in [
            (("bar", "image", 0, 0, 256, 16), {"file": "art:topbar/11.png"}),
            (("name", "text", 3, 2, 138, 12), {"text": "{host}", "color": "#ffffff"}),
            (("time", "text", 144, 2, 30, 12), {"text": "{time}", "color": "#ffffff", "align": "center"}),
            (("date", "text", 176, 2, 30, 12), {"text": "{date}", "color": "#ffffff", "align": "center"}),
            (("usb", "usb", 225, 4, 12, 7), {}),
            (("battery", "image", 242, 4, 12, 7), {"file": "art:battery/batteryfullDS.png"}),
        ]]}
        new = layout.validate({"elements": [layout._element("top_bar", "top_bar", 0, 0, 256, 16)]})
        theme, now = themes.BUILT_IN["Classic"], datetime(2026, 1, 2, 3, 4)
        draw = lambda l: np.asarray(widgets.render(themes.apply_layout(l, theme), Stats(), now))
        self.assertTrue(np.array_equal(draw(old), draw(new)))

    def test_a_missing_template_drops_only_its_element(self):
        saved = {"elements": [{"id": "x", "type": "gone_template", "x": 0, "y": 0, "w": 1, "h": 1},
                              {"id": "clock", "type": "clock", "x": 15, "y": 31, "w": 97, "h": 97}]}
        self.assertEqual([e["id"] for e in layout.validate(saved, lenient=True)["elements"]], ["clock"])

    def test_a_broken_template_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "bad.json").write_text("{not json")
            (Path(folder) / "ok.json").write_text(json.dumps({"type": "tiny", "label": "Tiny", "size": [8, 8], "props": [],
                                                             "children": [{"type": "panel", "x": 0, "y": 0, "w": 8, "h": 8}]}))
            with mock.patch.object(templates, "folders", return_value=[Path(folder)]):
                self.assertEqual(sorted(templates.load()), ["tiny"])


class DashboardTests(unittest.TestCase):
    def test_renders_every_month_shape(self):
        clean = layout.validate(layout.default_layout())
        for year, month, day in ((2026, 2, 1), (2026, 5, 31), (2026, 8, 1), (2026, 8, 31), (2024, 2, 29)):
            image = widgets.render(clean, Stats(), datetime(year, month, day, 12, 0, 0))
            self.assertEqual(image.size, (256, 384))

    def test_pixel_scale_is_measured_from_the_art(self):
        with tempfile.TemporaryDirectory() as folder:
            art = Image.effect_noise((10, 6), 90).convert("RGB")
            art.resize((100, 60), Image.NEAREST).save(Path(folder) / "scaled.png")
            art.save(Path(folder) / "plain.png")
            self.assertEqual(widgets.pixel_scale(Path(folder) / "scaled.png"), 10)
            self.assertEqual(widgets.pixel_scale(Path(folder) / "plain.png"), 1)

    def test_tokens_expand_and_unknown_ones_stay(self):
        self.assertEqual(widgets.expand_tokens("{time} {nope} {0.__class__}", {"time": "12:00"}),
                         "12:00 {nope} {0.__class__}")

    def test_broken_element_does_not_stop_rendering(self):
        clean = layout.validate(layout.default_layout())
        clean["elements"][0]["props"]["file"] = "art:uploads/missing.png"
        self.assertEqual(widgets.render(clean, Stats(), datetime(2026, 1, 1)).size, (256, 384))

    def test_hidden_elements_are_not_drawn(self):
        element = {"id": "a", "type": "panel", "x": 0, "y": 0, "w": 9, "h": 9, "props": {"fill": "#ffffff"}}
        clean = layout.validate({"elements": [element]})
        self.assertEqual(widgets.render(clean, Stats(), datetime(2026, 1, 1)).getpixel((4, 4)), (255, 255, 255))
        clean["elements"][0]["hidden"] = True
        self.assertEqual(widgets.render(clean, Stats(), datetime(2026, 1, 1)).getpixel((4, 4)), (0, 0, 0))


class AnimationScreenTests(unittest.TestCase):
    def test_our_copy_of_the_screen_is_only_the_live_picture(self):
        ds = device.DsDevice(open_port=None, list_ports=lambda: [])
        animation = device.Animation((10, 20, 6, 4), [(1, b"body")])
        ds._animations = [animation]
        ds._animation_packets([animation])
        self.assertTrue((ds._screen == codec.BLACK).all())

        ds._frame_packets(np.full((codec.HEIGHT, codec.WIDTH), 0x8123, dtype=np.uint16))
        self.assertTrue((ds._screen == 0x8123).all())


class CalendarTests(unittest.TestCase):
    def test_marks_today(self):
        element = {"x": 0, "y": 0, "w": 113, "h": 97, "props": {"today_color": "#005af6", "text_color": "#424242"}}
        canvas = Image.new("RGB", (256, 192), "#ffffff")
        elements.MODULES["calendar"].draw(canvas, element, None, datetime(2026, 11, 7))
        # The 7th is a Saturday, in the first row and last column.
        self.assertEqual(canvas.getpixel((6 * 16 + 8, 16 + 3)), (209, 225, 253))


class ThemeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        self.path = self.data / "themes.json"
        self.user_dir = self.data / "themes"
        art = layout.ART_DIR
        self.addCleanup(setattr, layout, "ART_DIR", art)
        self.store = self.reopen()
        self.own = {"paper": "#102030", "ink": "#ffffff", "boost": 10, "lift": 0, "bar": 3}

    def reopen(self):
        return themes.ThemeStore(self.data)

    def test_classic_leaves_the_frame_alone(self):
        frame = Image.new("RGB", (4, 4), "#808080")
        self.assertIs(themes.apply_tone(frame, {"elements": []}, themes.BUILT_IN["Classic"]), frame)

    def test_dark_swaps_paper_and_ink_but_keeps_colours_hue(self):
        frame = Image.new("RGB", (3, 1), "#ffffff")
        frame.putpixel((1, 0), (0, 0, 0))
        frame.putpixel((2, 0), (200, 0, 0))
        out = themes.apply_tone(frame, {"elements": []}, themes.BUILT_IN["Dark"])
        self.assertEqual(out.getpixel((0, 0)), (0x1f, 0x20, 0x23))
        self.assertEqual(out.getpixel((1, 0)), (0xf4, 0xf4, 0xf6))
        red = out.getpixel((2, 0))
        self.assertGreater(red[0], red[1])

    def test_top_bar_keeps_its_white_text(self):
        element = {"x": 0, "y": 0, "w": 2, "h": 1, "hidden": False, "props": {"file": "art:topbar/11.png"}}
        out = themes.apply_tone(Image.new("RGB", (2, 2), "#ffffff"), {"elements": [element]}, themes.BUILT_IN["Dark"])
        self.assertEqual(out.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(out.getpixel((0, 1)), (0x1f, 0x20, 0x23))

    def test_bar_colour_reaches_the_art_and_accents(self):
        source = {"elements": [{"props": {"file": "art:topbar/11.png"}}, {"props": {"second_color": layout.PROFILE_COLOUR}}]}
        out = themes.apply_layout(source, self.own)
        self.assertEqual(out["elements"][0]["props"]["file"], "art:topbar/3.png")
        self.assertEqual(out["elements"][1]["props"]["second_color"], themes.profile_colour(3))
        self.assertEqual(source["elements"][0]["props"]["file"], "art:topbar/11.png")

    def test_saved_themes_survive_a_restart(self):
        self.store.save("Mine", self.own)
        again = self.reopen()
        self.assertEqual(again.active_name, "Mine")
        self.assertEqual(again.active, self.own)

    def test_each_theme_is_a_folder_with_all_its_art(self):
        for name, folder in self.store.built_in.items():
            with self.subTest(name):
                self.assertTrue((folder / "topbar" / "11.png").is_file())
                self.assertFalse((folder / "sound").exists(), "The page's own sounds and art aren't part of a theme")
        self.store.save("Mine", self.own)
        folder = self.store.custom["Mine"]
        self.assertEqual(folder, self.user_dir / "mine")
        self.assertTrue((folder / "topbar" / "11.png").is_file())
        self.assertEqual(json.loads((folder / "theme.json").read_text())["name"], "Mine")

    def test_a_theme_can_be_exported_and_imported(self):
        self.store.save("Mine", self.own)
        (self.store.uploads_dir() / "cat.png").parent.mkdir(exist_ok=True)
        Image.new("RGB", (2, 2)).save(self.store.uploads_dir() / "cat.png")
        packed = self.store.export("Mine")
        other = themes.ThemeStore(self.data / "elsewhere")
        self.assertEqual(other.import_zip(packed), "Mine")
        self.assertEqual((other.active_name, other.active), ("Mine", self.own))
        self.assertTrue((other.folder / "uploads" / "cat.png").is_file())
        self.assertEqual(other.layout, self.store.layout)
        self.assertEqual(other.import_zip(packed), "Mine 2", "A taken name gets a number")

    def test_an_import_can_only_write_images_inside_its_folder(self):
        import io, zipfile
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w") as archive:
            archive.writestr("theme.json", json.dumps({"name": "Sneaky", **self.own}))
            archive.writestr("../outside.png", b"x")
            archive.writestr("uploads/run.exe", b"x")
            archive.writestr("uploads/fine.png", b"x")
        self.store.import_zip(packed.getvalue())
        folder = self.store.custom["Sneaky"]
        self.assertEqual(sorted(path.name for path in folder.rglob("*") if path.is_file()), ["fine.png", "theme.json"])
        self.assertFalse((self.user_dir / "outside.png").exists())
        for bad in (b"not a zip", b""):
            with self.assertRaises(ValueError):
                self.store.import_zip(bad)

    def test_old_built_in_art_in_a_copy_is_replaced(self):
        self.store.save("Mine", self.own)
        file = self.store.custom["Mine"] / "quickmenu" / "topbg.png"
        fixed = file.read_bytes()
        with mock.patch.dict(themes.OLD_ART, {"quickmenu/topbg.png": __import__("hashlib").sha1(b"old").hexdigest()}):
            file.write_bytes(b"old")
            self.reopen()
            self.assertEqual(file.read_bytes(), fixed)
            file.write_bytes(b"my own")
            self.reopen()
            self.assertEqual(file.read_bytes(), b"my own", "Art the user changed is left alone")

    def test_art_comes_from_the_active_theme(self):
        self.store.save("Mine", self.own)
        self.assertEqual(layout.resolve_file("art:grf/box.bmp"), (self.user_dir / "mine" / "grf" / "box.bmp").resolve())
        self.store.use("Dark")
        self.assertEqual(layout.resolve_file("art:grf/box.bmp").parent.parent, self.store.built_in["Dark"].resolve())
        self.store.delete("Mine")
        self.assertFalse((self.user_dir / "mine").exists())

    def test_old_saved_themes_become_folders(self):
        self.path.write_text(json.dumps({"active": "Old", "themes": {"Old": self.own}}), encoding="utf-8")
        store = self.reopen()
        self.assertEqual(store.active_name, "Old")
        self.assertEqual(store.active, self.own)
        self.assertTrue((store.custom["Old"] / "grf" / "box.bmp").is_file())
        store.use("Old")
        self.assertEqual(json.loads(self.path.read_text()), {"active": "Old"})

    def test_changing_a_built_in_theme_changes_a_copy_that_reset_removes(self):
        original = themes.read(self.store.built_in["Dark"])
        self.store.save("Dark", self.own)
        self.assertEqual(self.store.folder, self.user_dir / "dark")
        self.assertEqual(themes.read(self.store.built_in["Dark"]), original)
        self.assertEqual(self.reopen().active, self.own)
        self.store.delete("Dark")
        self.assertEqual(self.store.active, original)
        self.assertFalse((self.user_dir / "dark").exists())
        with self.assertRaises(ValueError):
            self.store.delete("Classic")

    def test_each_theme_has_its_own_layout(self):
        mine = layout.validate({"elements": [{"id": "only", "type": "text", "x": 1, "y": 2, "w": 30, "h": 12, "props": {}}]})
        self.store.save("Mine", self.own)
        self.store.save_layout(mine)
        self.assertEqual(self.reopen().layout, mine)
        self.store.use("Classic")
        self.assertEqual(self.store.layout, layout.validate(layout.default_layout()))
        self.assertEqual(themes.read_layout(self.store.built_in["Classic"]), self.store.layout)
        self.store.save("Copy", self.own)      # From Classic, so with its layout
        self.assertEqual(self.store.layout, layout.validate(layout.default_layout()))

    def test_sleep_screen_is_part_of_the_theme(self):
        self.assertEqual(self.store.sleep, {"file": "art:sleep/sleepy_cat.gif", "screen": "top", "brightness": 30})
        self.assertTrue(layout.resolve_file(self.store.sleep["file"]).is_file())
        self.store.set_sleep({"file": "", "screen": "bottom", "brightness": 10})
        self.assertEqual(self.store.folder, self.user_dir / "classic")
        self.assertEqual(self.reopen().sleep, {"file": "", "screen": "bottom", "brightness": 10})
        for bad in ({"file": "art:grf/box.bmp"}, {"screen": "left"}, {"brightness": 101}, {"file": "art:../x.gif"}):
            with self.assertRaises(ValueError):
                self.store.set_sleep(bad)

    def test_older_saved_themes_get_a_sleep_screen(self):
        self.store.save("Mine", self.own)
        folder = self.store.custom["Mine"]
        info = json.loads((folder / "theme.json").read_text())
        del info["sleep"]
        (folder / "theme.json").write_text(json.dumps(info))
        shutil.rmtree(folder / "sleep")
        store = self.reopen()
        self.assertEqual(store.sleep["file"], "art:sleep/sleepy_cat.gif")
        self.assertTrue((folder / "sleep" / "sleepy_cat.gif").is_file())

    def test_uploads_go_in_the_theme(self):
        self.store.use("Dark")
        folder = self.store.uploads_dir()
        self.assertEqual(folder, self.user_dir / "dark" / "uploads")

    def test_the_old_shared_layout_and_uploads_move_into_the_themes(self):
        old = layout.validate(layout.default_layout())
        old["elements"] = old["elements"][:3]
        shared = json.loads(json.dumps(old))
        shared["elements"][0]["props"]["file"] = "local:mine.png"
        (self.data / "layout.json").write_text(json.dumps(shared), encoding="utf-8")
        Image.new("RGB", (2, 2)).save(self.data / "mine.png")
        self.path.write_text(json.dumps({"active": "Dark", "themes": {"Old": self.own}}), encoding="utf-8")
        store = self.reopen()
        self.assertEqual(store.active_name, "Dark")
        for name in ("Dark", "Old"):
            with self.subTest(name):
                store.use(name)
                self.assertEqual(store.layout["elements"][0]["props"]["file"], "art:uploads/mine.png")
                self.assertTrue((store.folder / "uploads" / "mine.png").is_file())
        self.assertFalse((self.data / "layout.json").exists())
        self.assertTrue((self.data / "layout.json.old").exists())

    def test_deleting_the_active_theme_falls_back(self):
        self.store.save("Mine", self.own)
        self.store.delete("Mine")
        self.assertEqual(self.store.active_name, "Classic")

    def test_refuses_bad_values(self):
        for bad in ({**self.own, "paper": "red"}, {**self.own, "bar": 16}, {**self.own, "boost": True}):
            with self.assertRaises(ValueError):
                themes.clean(bad)

    def test_a_broken_file_is_ignored(self):
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(self.reopen().active_name, "Classic")


class FakeNvml:
    """Stands in for nvml.dll, filling in what each call asks for."""
    def __init__(self, failing=()):
        self.failing = failing

    def nvmlInit_v2(self):
        return 0

    def nvmlDeviceGetHandleByIndex_v2(self, index, handle):
        return 0

    def nvmlDeviceGetUtilizationRates(self, handle, out):
        if "load" in self.failing:
            return 3
        out._obj.gpu = 42
        return 0

    def nvmlDeviceGetMemoryInfo(self, handle, out):
        out._obj.used = 3 * 2**30
        return 0

    def nvmlDeviceGetTemperature(self, handle, sensor, out):
        out._obj.value = 66
        return 0


class GpuTests(unittest.TestCase):
    def test_load_is_the_busiest_engine_summed_over_processes(self):
        name = "pid_{}_luid_0x0_0x1_phys_0_eng_{}_engtype_{}"
        samples = {name.format(1, 0, "3D"): 20.0, name.format(2, 0, "3D"): 15.0, name.format(1, 3, "Copy"): 30.0}
        self.assertEqual(gpu.busiest_engine(samples), 35.0)

    def test_load_is_capped(self):
        self.assertEqual(gpu.busiest_engine({"luid_0x0_phys_0_eng_0_a": 90.0, "x_luid_0x0_phys_0_eng_0_b": 40.0}), 100.0)

    def test_memory_is_the_busiest_adapter(self):
        dedicated = {"luid_0x1_phys_0": 100.0, "luid_0x2_phys_0": 0.0}
        shared = {"luid_0x1_phys_0": 50.0, "luid_0x2_phys_0": 120.0}
        self.assertEqual(gpu.adapter_memory(dedicated, shared), 150.0)

    def test_temperature_ignores_nonsense_zones(self):
        self.assertAlmostEqual(gpu.hottest_celsius({"a": 3162.0, "b": 0.0, "c": 9000.0}), 43.05)

    def test_nothing_reported_is_none(self):
        self.assertIsNone(gpu.busiest_engine({}))
        self.assertIsNone(gpu.hottest_celsius({}))

    def test_nvml_values(self):
        nvml = gpu.Nvml(load=lambda path: FakeNvml())
        self.assertEqual(nvml.read(), (42.0, 3.0 * 2**30, 66.0))

    def test_a_failed_nvml_reading_is_none(self):
        nvml = gpu.Nvml(load=lambda path: FakeNvml(failing=("load",)))
        self.assertIsNone(nvml.read()[0])

    def test_no_nvml_is_harmless(self):
        def missing(path):
            raise OSError
        self.assertEqual(gpu.Nvml(load=missing).read(), (None, None, None))

    def test_nvml_wins_and_counters_fill_the_gaps(self):
        self.assertEqual(gpu.merge((42.0, None, 66.0), (1.0, 2.0, 43.0)), (42.0, 2.0, 66.0))


class TemperatureTests(unittest.TestCase):
    def colours(self, temperature):
        element = {"x": 0, "y": 0, "w": 80, "h": 12, "props": {"text": "T ", "size": "10", "color": "#424242"}}
        canvas = Image.new("RGB", (80, 12), "#ffffff")
        elements.MODULES["temperature"].draw(canvas, element, widgets.Stats(temperature=temperature), datetime(2026, 1, 1))
        return {c for _, c in canvas.getcolors(9999)}

    def test_colour_follows_the_heat(self):
        self.assertIn((0x42, 0x42, 0x42), self.colours(50))
        self.assertIn((0xe0, 0x70, 0x00), self.colours(75))
        self.assertIn((0xd3, 0x00, 0x00), self.colours(90))

    def test_unknown_shows_dashes(self):
        stats = widgets.Stats()
        self.assertEqual(widgets.token_values(stats, datetime(2026, 1, 1))["temp"], "--")
        self.assertEqual(widgets.token_values(stats, datetime(2026, 1, 1))["gpu"], "--")


class UsbIconTests(unittest.TestCase):
    def colour(self, connected):
        element = {"x": 0, "y": 0}
        canvas = Image.new("RGB", (16, 16))
        elements.MODULES["usb"].draw(canvas, element, SimpleNamespace(usb_connected=connected), None)
        return canvas.getpixel((0, 3))

    def test_shows_the_link_state(self):
        self.assertGreater(self.colour(True)[1], self.colour(True)[0])
        self.assertGreater(self.colour(False)[0], self.colour(False)[1])


class ServerTests(unittest.TestCase):
    def test_accepts_a_burst_of_connections(self):
        from dsdash.server import Server
        self.assertGreaterEqual(Server.request_queue_size, 64)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        from dsdash.server import create_server
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = create_server(SimpleNamespace(status=lambda: {"ok": True}), self.port)
        threading.Thread(target=self.server.serve_forever, args=(.01,), daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(self.client.close)

    def test_reuses_the_connection(self):
        self.client.request("GET", "/api/status")
        self.assertEqual(self.client.getresponse().read(), b'{"ok": true}')
        first = self.client.sock
        self.client.request("GET", "/api/status")
        self.assertEqual(self.client.getresponse().status, 200)
        self.assertIs(self.client.sock, first)

    def test_answers_on_ipv6_too(self):
        client = http.client.HTTPConnection("::1", self.port, timeout=5)
        self.addCleanup(client.close)
        client.request("GET", "/api/status", headers={"Host": f"localhost:{self.port}"})
        self.assertEqual(client.getresponse().status, 200)

    def test_closes_when_a_body_is_left_unread(self):
        self.client.request("POST", "/api/layout", body=b"{}", headers={"Host": "example.com"})
        response = self.client.getresponse()
        response.read()
        self.assertEqual(response.status, 403)
        self.assertIsNone(self.client.sock)

    def test_a_closing_response_arrives_whole_for_a_slow_reader(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as client:
            client.sendall(b"GET /api/status HTTP/1.1\r\nHost: example.com\r\n\r\n")
            time.sleep(.2)
            reply = client.recv(4096)
        self.assertIn(b"403", reply)
        self.assertIn(b"Forbidden host", reply)

    def test_an_idle_connection_ends_with_a_reset(self):
        self.server.RequestHandlerClass.timeout = .05
        with mock.patch("dsdash.server.HANG_UP_SECONDS", .05):
            with socket.create_connection(("127.0.0.1", self.port), timeout=5) as client:
                with self.assertRaises(ConnectionResetError):
                    client.recv(1)


class RevisionTests(unittest.TestCase):
    def setUp(self):
        from dsdash.app import App
        from dsdash.server import create_server
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for name, value in (("LOCAL_DIR", Path(folder.name)), ("ART_DIR", layout.ART_DIR)):
            patcher = mock.patch.object(layout, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = App()
        self.saved = lambda: self.app.themes.folder / "theme.json"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        self.server = create_server(self.app, self.port)
        threading.Thread(target=self.server.serve_forever, args=(.01,), daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, body=None, revision=None):
        client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(client.close)
        headers = {} if revision is None else {"X-Layout-Revision": str(revision)}
        client.request(method, path, body=body, headers=headers)
        response = client.getresponse()
        return response.status, json.loads(response.read()), response.getheader("X-Layout-Revision")

    def post(self, revision=None):
        return self.call("POST", "/api/layout", json.dumps(self.app.layout), revision)

    def test_every_save_raises_the_revision(self):
        status, _, first = self.call("GET", "/api/layout")
        self.assertEqual(status, 200)
        _, _, second = self.post(first)
        _, _, third = self.call("POST", "/api/layout/reset", revision=second)
        self.assertEqual([int(second), int(third)], [int(first) + 1, int(first) + 2])
        self.assertEqual(self.call("GET", "/api/status")[1]["layoutRevision"], int(third))

    def test_an_out_of_date_save_is_refused(self):
        _, _, seen = self.call("GET", "/api/layout")
        self.post(seen)
        before = self.saved().read_bytes()
        stale = dict(self.app.layout, elements=[])
        status, body, latest = self.call("POST", "/api/layout", json.dumps(stale), seen)
        self.assertEqual(status, 409)
        self.assertIn("error", body)
        self.assertEqual(int(latest), int(seen) + 1)
        self.assertEqual(self.saved().read_bytes(), before)
        self.assertTrue(self.app.layout["elements"])

    def fetch(self, path):
        client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(client.close)
        client.request("GET", path)
        response = client.getresponse()
        return response, response.read()

    def test_the_big_font_is_cached_and_live_data_is_not(self):
        self.assertIn("max-age=", self.fetch("/font.otf")[0].getheader("Cache-Control"))
        self.assertIn("max-age=", self.fetch("/web/vendor/motion.js")[0].getheader("Cache-Control"))
        for path in ("/web/app.js", "/api/status", "/api/frame.png"):
            self.assertEqual(self.fetch(path)[0].getheader("Cache-Control"), "no-store", path)

    def test_the_picture_has_a_number_that_only_changes_with_it(self):
        response, first = self.fetch("/api/frame.png")
        number = response.getheader("X-Frame")
        self.assertEqual(self.call("GET", "/api/status")[1]["frame"], int(number))
        again, second = self.fetch("/api/frame.png")
        self.assertEqual((again.getheader("X-Frame"), second), (number, first))

    def test_the_status_is_pushed_as_events(self):
        client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(client.close)
        client.request("GET", "/api/events")
        response = client.getresponse()
        self.assertEqual(response.getheader("Content-Type"), "text/event-stream")
        line = response.fp.readline()
        self.assertTrue(line.startswith(b"data: "))
        self.assertEqual(json.loads(line[6:])["layoutRevision"], self.app.revision)

    def test_each_theme_has_a_picture_and_a_zip(self):
        response, picture = self.fetch("/api/theme.png?name=Dark")
        self.assertEqual(response.status, 200)
        self.assertEqual(Image.open(__import__("io").BytesIO(picture)).size, (128, 192))
        self.assertEqual(layout.ART_DIR, self.app.themes.folder, "Drawing another theme leaves the active one's art in place")
        response, packed = self.fetch("/api/theme.zip?name=Classic")
        self.assertIn("Classic.zip", response.getheader("Content-Disposition"))
        client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(client.close)
        client.request("POST", "/api/themes/import", packed)
        listing = json.loads(client.getresponse().read())
        self.assertEqual(listing["active"], "Classic 2")
        self.assertEqual(self.fetch("/api/theme.png?name=Nope")[0].status, 404)

    def test_the_firmware_update_waits_for_an_answer(self):
        self.app.firmware.offer = {"running": 17}
        self.assertEqual(self.call("GET", "/api/status")[1]["firmwareOffer"], {"running": 17})
        status, body, _ = self.call("POST", "/api/firmware", json.dumps({"update": True}))
        self.assertEqual((status, body["firmwareOffer"]), (200, None))
        self.assertTrue(self.app.firmware._allowed)
        self.assertIsNone(self.call("GET", "/api/status")[1]["update"])

    def test_the_sleep_screen_says_where_its_gif_goes(self):
        listing = self.call("GET", "/api/themes")[1]
        box = listing["sleepBox"]
        self.assertEqual(box["x"], (256 - box["w"]) // 2)
        self.assertLessEqual(box["y"] + box["h"], 192)
        self.assertEqual(len(box["crop"]), 4)

    def test_colours_save_to_the_theme_without_touching_the_layout(self):
        before = self.app.revision
        theme = {"paper": "#102030", "ink": "#ffffff", "boost": 10, "lift": 0, "bar": 3}
        status, listing, _ = self.call("POST", "/api/themes", json.dumps({"action": "colours", "theme": theme}))
        self.assertEqual((status, listing["themes"][listing["active"]]), (200, theme))
        self.assertEqual(self.app.revision, before)
        self.assertEqual(themes.read(self.app.themes.folder), theme)

    def test_an_out_of_date_reset_is_refused(self):
        _, _, seen = self.call("GET", "/api/layout")
        self.post(seen)
        self.assertEqual(self.call("POST", "/api/layout/reset", revision=seen)[0], 409)

    def test_a_save_without_a_revision_still_works(self):
        before = self.app.revision
        self.assertEqual(self.post()[0], 200)
        self.assertEqual(self.call("POST", "/api/layout/reset")[0], 200)
        self.assertEqual(self.app.revision, before + 2)

    def test_a_refused_or_invalid_save_keeps_the_revision(self):
        before = self.app.revision
        self.assertEqual(self.post(before - 1)[0], 409)
        self.assertEqual(self.call("POST", "/api/layout", b"{}", before)[0], 400)
        self.assertEqual(self.post("soon")[0], 400)
        self.assertEqual(self.app.revision, before)

    def test_the_revision_stays_out_of_the_layout(self):
        _, body, seen = self.post(self.app.revision)
        self.assertNotIn(seen, json.dumps(body))
        saved = json.loads(self.saved().read_text(encoding="utf-8"))["layout"]
        self.assertEqual(saved, body)
        self.assertNotIn("revision", json.dumps(saved).lower())

    def test_only_one_of_several_racing_saves_wins(self):
        seen = self.app.revision
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.post(seen)[0])) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), [200, 409, 409, 409])
        self.assertEqual(self.app.revision, seen + 1)

    def test_a_restart_starts_from_a_higher_revision(self):
        from dsdash.app import App
        time.sleep(.01)
        self.assertGreater(App().revision, self.app.revision)


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.keeper = firmware.FirmwareKeeper()
        patcher = mock.patch.object(firmware, "rom_crc", return_value=0x1234)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(firmware.dsctl, "upload_and_boot")
        self.push = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(firmware.dsctl, "install_on_sd", return_value="D:/apps/x.nds")
        self.install = patcher.start()
        self.addCleanup(patcher.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(firmware, "SD_RECORD", Path(folder.name) / "firmware.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.keeper.answer(True)    # Most tests are about what happens once the update is agreed to

    def test_asks_before_updating(self):
        keeper = firmware.FirmwareKeeper()
        keeper.check(self.link(0x9999), b"rom")
        self.push.assert_not_called()
        self.assertEqual(keeper.offer, {"running": 7})
        keeper.answer(True)
        self.assertIsNone(keeper.offer)
        keeper.check(self.link(0x9999), b"rom")
        self.push.assert_called_once()

    def test_a_no_lasts_for_the_run(self):
        keeper = firmware.FirmwareKeeper()
        keeper.check(self.link(0x9999), b"rom")
        keeper.answer(False)
        keeper.check(self.link(0x9999), b"rom")
        self.push.assert_not_called()
        self.assertIsNone(keeper.offer)
        self.assertIn("skipped", keeper.state)

    def link(self, crc):
        return SimpleNamespace(request=lambda op: struct.pack("<7I", 3, crc, 0, 0, 0, 0, 7))

    def test_asks_for_a_new_build_to_go_on_the_sd_card(self):
        self.assertEqual(self.keeper.check(self.link(0x1234), b"rom"), 7)

    def test_only_copies_to_the_sd_card_once(self):
        self.keeper.install(b"rom", "x.nds", 7)
        self.install.assert_called_once_with(b"rom", "x.nds")
        self.assertIsNone(self.keeper.check(self.link(0x1234), b"rom"))

    def test_trusts_the_sd_card_after_a_power_cycle(self):
        self.keeper.install(b"rom", "x.nds", 7)
        self.assertIsNone(self.keeper.check(self.link(0), b"rom"))
        self.push.assert_not_called()
        self.assertIn("Current", self.keeper.state)

    def test_pushes_when_the_sd_card_has_another_build(self):
        firmware.SD_RECORD.write_text('{"crc": 1, "build": 7}')
        self.keeper.check(self.link(0), b"rom")
        self.push.assert_called_once()

    def test_gives_up_on_a_failed_copy_until_the_next_run(self):
        self.install.side_effect = firmware.dsctl.DsError("no card")
        self.keeper.install(b"rom", "x.nds", 7)
        self.assertIn("no card", self.keeper.state)
        self.assertFalse(firmware.SD_RECORD.exists())
        self.assertIsNone(self.keeper.check(self.link(0x1234), b"rom"))

    def test_leaves_a_current_ds_alone(self):
        self.keeper.check(self.link(0x1234), b"rom")
        self.push.assert_not_called()
        self.assertIn("Current", self.keeper.state)

    def test_pushes_when_behind(self):
        self.keeper.check(self.link(0x9999), b"rom")
        self.push.assert_called_once()

    def test_pushes_over_an_early_build(self):
        self.keeper.check(SimpleNamespace(request=lambda op: struct.pack("<6I", 1, 0, 0, 0, 0, 0)), b"rom")
        self.push.assert_called_once()

    def test_does_not_loop_if_a_push_does_not_stick(self):
        self.keeper.check(self.link(0x9999), b"rom")
        self.keeper.check(self.link(0x9999), b"rom")
        self.push.assert_called_once()

    def test_pushes_again_after_a_power_cycle(self):
        self.keeper.check(self.link(0x9999), b"rom")
        self.keeper.check(self.link(0x1234), b"rom")
        self.keeper.check(self.link(0), b"rom")
        self.assertEqual(self.push.call_count, 2)


class UpdateTests(unittest.TestCase):
    URL = "https://github.com/tinkerizer/dspico-usb-display/releases/tag/v1.4.0"

    def test_a_newer_release_is_offered_with_its_page(self):
        found = updates.newer({"tag_name": "v1.4.0", "html_url": self.URL}, "1.3.0")
        self.assertEqual(found, {"version": "1.4.0", "url": self.URL})
        self.assertEqual(updates.newer({"tag_name": "v1.10.0", "html_url": self.URL}, "1.9.9")["version"], "1.10.0")

    def test_the_same_or_an_older_release_is_not(self):
        for tag in ("v1.3.0", "v1.2.9", "1.3.0"):
            self.assertIsNone(updates.newer({"tag_name": tag, "html_url": self.URL}, "1.3.0"), tag)

    def test_anything_unexpected_is_ignored(self):
        for release in ({}, {"tag_name": "nightly", "html_url": self.URL}, {"tag_name": "v9.0.0"},
                        {"tag_name": "v9.0.0", "html_url": "https://example.com/setup.exe"},
                        {"tag_name": "v9.0.0", "html_url": "javascript:alert(1)"}, {"tag_name": 9, "html_url": self.URL}):
            self.assertIsNone(updates.newer(release, "1.3.0"), release)
        self.assertIsNone(updates.newer({"tag_name": "v9.0.0", "html_url": self.URL}, "unknown"))


class InstallerTests(unittest.TestCase):
    def test_waits_for_a_locked_exe(self):
        with mock.patch.object(installer.shutil, "copy2", side_effect=[PermissionError, PermissionError, None]) as copy, \
                mock.patch.object(installer.time, "sleep"):
            installer._replace_exe()
        self.assertEqual(copy.call_count, 3)

    def test_gives_up_if_the_exe_stays_locked(self):
        with mock.patch.object(installer.shutil, "copy2", side_effect=PermissionError) as copy, \
                mock.patch.object(installer.time, "sleep"):
            with self.assertRaises(PermissionError):
                installer._replace_exe()
        self.assertEqual(copy.call_count, installer.COPY_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
