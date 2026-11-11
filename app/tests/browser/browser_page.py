"""The shell colour picker, and loading the page again and again."""
import base64
import unittest
from io import BytesIO

import numpy as np
from PIL import Image

import harness
from harness import HAS_ART, NEXT_PAINT, BrowserCase, decode, wait_ready

SWATCHES = {"Black": "#3d3d3d", "White": "#e4e4e6", "Silver": "#a9adb3", "Red": "#b3202a",
            "Pink": "#e58fb0", "Blue": "#23549e", "Teal": "#1f8a8a", "Gold": "#c29a3f"}
PALE = {"White", "Silver", "Pink", "Gold"}
DARK_LABEL, PALE_LABEL = "#e8e8e8", "#3d3d3d"
STATE = """(() => {
  const style = document.documentElement.style;
  return {
    colour: style.getPropertyValue('--ds-color'),
    label: style.getPropertyValue('--ds-label'),
    stored: localStorage.getItem('shellColour'),
    input: document.getElementById('shellColour').value,
    pressed: [...document.querySelectorAll('#swatches .shell-swatch[aria-pressed=true]')].map(swatch => swatch.title),
  };
})()"""


def css(page, name):
    return page.evaluate("name => document.documentElement.style.getPropertyValue(name)", name)


def stored(page):
    return page.evaluate("localStorage.getItem('shellColour')")


def rgb(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def pick(page, name):
    page.click(f".shell-swatch[title={name}]")


class ShellColourTests(BrowserCase):
    def test_swatches_set_the_colour_and_the_label(self):
        page = self.open()
        self.assertEqual(page.locator("#swatches .shell-swatch").count(), len(SWATCHES))
        for name, colour in SWATCHES.items():
            with self.subTest(name):
                page.click(f".shell-swatch[title={name}]")
                self.assertEqual(page.evaluate(STATE), {
                    "colour": colour, "stored": colour, "input": colour, "pressed": [name],
                    "label": PALE_LABEL if name in PALE else DARK_LABEL,
                })

    def test_the_shell_itself_changes_colour(self):
        page = self.open()
        pick(page, "Red")
        page.evaluate(NEXT_PAINT)
        rect = page.evaluate("""(({ left, width }, { top, height }) => ({ x: left + width * .1, y: top + height / 2, width: 4, height: 4 }))
          (document.querySelector('.console').getBoundingClientRect(), document.querySelector('.lcd.top').getBoundingClientRect())""")
        red, green, blue = decode(page.screenshot(clip=rect))[1, 1].astype(int)
        self.assertGreater(red, green + 60, "The shell doesn't look red")
        self.assertGreater(red, blue + 60, "The shell doesn't look red")

        pick(page, "White")
        fill = page.evaluate("getComputedStyle(document.querySelector('#shellArt .ink')).fill")
        self.assertEqual(fill, f"rgb({', '.join(map(str, rgb(PALE_LABEL)))})")

    def test_custom_colour_and_swatch_survive_a_reload(self):
        page = self.open()
        page.locator("#shellColour").fill("#123456")
        wanted = {"colour": "#123456", "stored": "#123456", "input": "#123456", "pressed": [], "label": DARK_LABEL}
        self.assertEqual(page.evaluate(STATE), wanted)
        self.reload(page)
        self.assertEqual(page.evaluate(STATE), wanted)

        pick(page, "Teal")
        self.reload(page)
        colour = SWATCHES["Teal"]
        self.assertEqual(page.evaluate(STATE), {"colour": colour, "stored": colour, "input": colour,
                                                "pressed": ["Teal"], "label": DARK_LABEL})

    def test_bad_stored_colour_falls_back(self):
        page = self.open()
        for bad in ("red", "#12345", "#gggggg", "#123456;color:red"):
            with self.subTest(bad):
                page.evaluate("bad => localStorage.setItem('shellColour', bad)", bad)
                self.reload(page)
                self.assertEqual(css(page, "--ds-color"), SWATCHES["Black"])
                self.assertEqual(page.input_value("#shellColour"), SWATCHES["Black"])

    @unittest.skipUnless(HAS_ART, "Needs the stylus art")
    def test_cursor_tint_follows_the_colour(self):
        page = self.open()
        page.wait_for_function("document.documentElement.style.getPropertyValue('--stylus').includes('data:image/png')")
        grey = np.asarray(Image.open(harness.REPO / "app" / "dsdash" / "web" / "ui" / "stylus.png").convert("RGBA"))
        body = (grey[..., 0] == 128) & (grey[..., 3] == 255)
        self.assertGreater(int(body.sum()), 0)

        seen = set()
        for name in ("Red", "Blue", "White"):
            with self.subTest(name):
                pick(page, name)
                value = css(page, "--stylus")
                seen.add(value)
                data = base64.b64decode(value.split("base64,")[1].split(")")[0])
                tinted = np.asarray(Image.open(BytesIO(data)).convert("RGBA"))
                self.assertEqual(tinted.shape, grey.shape)
                self.assertTrue((tinted[body][:, :3] == rgb(SWATCHES[name])).all(), "The stylus body isn't the shell colour")
                self.assertTrue((tinted[..., 3] == grey[..., 3]).all(), "The stylus changed shape")
                self.assertIn("data:image/png", page.evaluate("getComputedStyle(document.documentElement).cursor"))
        self.assertEqual(len(seen), 3)

        self.reload(page)
        page.wait_for_function("value => document.documentElement.style.getPropertyValue('--stylus') === value",
                               arg=value)


class ShellButtonTests(BrowserCase):
    def shell(self, name):
        page = self.open()
        page.evaluate("name => setShellModel(name)", name)
        page.wait_for_function("name => !!document.querySelector('.shell .press') && (name === 'dsi') === !!document.querySelector('.shell .lens')", arg=name)
        page.evaluate("(() => { window.played = []; const real = Effects.play; Effects.play = name => { window.played.push(name); real(name); }; })()")
        self.addCleanup(lambda: page.evaluate("setShellModel('lite')"))
        return page

    def centre(self, page, selector):
        box = page.locator(selector).first.bounding_box()
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, box

    def test_buttons_press_and_click(self):
        for name, count in (("lite", 7), ("dsi", 8)):
            with self.subTest(shell=name):
                page = self.shell(name)
                self.assertEqual(page.locator(".press").count(), count)
                for index in range(count):
                    control = page.locator(".press").nth(index)
                    control.scroll_into_view_if_needed()
                    box = control.locator(".button, .flat-button, .dpad, .power").first.bounding_box()
                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    page.mouse.down()
                    self.assertIn("down", control.get_attribute("class"))
                    page.mouse.up()
                    self.assertNotIn("down", control.get_attribute("class"))
                self.assertEqual(len(page.evaluate("window.played")), count)

    def test_shell_art_stays_inside_the_shell(self):
        # A shell class that clashes with a page class, such as .lcd, gets the page's layout.
        for name in ("lite", "dsi"):
            with self.subTest(shell=name):
                page = self.shell(name)
                spill = page.evaluate("""() => {
                    const shell = document.querySelector('#shellArt svg').getBoundingClientRect();
                    return [...document.querySelectorAll('#shellArt svg *')].filter(e => e.getBoundingClientRect).filter(e => {
                        const r = e.getBoundingClientRect();
                        return r.width && (r.left < shell.left - 30 || r.right > shell.right + 30
                            || r.top < shell.top - 30 || r.bottom > shell.bottom + 30);
                    }).map(e => e.outerHTML.slice(0, 80));
                }""")
                self.assertEqual(spill, [])

    def test_dpad_rocks_towards_the_arm(self):
        page = self.shell("lite")
        page.locator(".dpad").scroll_into_view_if_needed()
        x, y, box = self.centre(page, ".dpad")
        for dx, dy, expected in ((0, -.4, ("0px", "-1.2px")), (.4, 0, ("1.2px", "0px"))):
            page.mouse.move(x + box["width"] * dx, y + box["height"] * dy)
            page.mouse.down()
            press = page.evaluate("(() => { const s = document.querySelector('.press').style; return [s.getPropertyValue('--press-x'), s.getPropertyValue('--press-y')]; })()")
            page.mouse.up()
            self.assertEqual(tuple(press), expected)

    @unittest.skipUnless(HAS_ART, "The stylus art isn't committed")
    def test_stylus_reacts_to_a_press(self):
        context, page, _ = harness.new_page()
        self.addCleanup(context.close)
        page.emulate_media(reduced_motion="no-preference")    # The ring skips itself otherwise.
        page.goto(harness.url)
        wait_ready(page)
        page.wait_for_function("stylusUp !== null")
        up = page.evaluate("document.documentElement.style.getPropertyValue('--stylus')")
        page.mouse.move(40, 300)
        page.mouse.down()
        self.assertNotEqual(page.evaluate("document.documentElement.style.getPropertyValue('--stylus')"), up)
        ring = """() => { const c = document.querySelector('canvas.effects'), r = devicePixelRatio;
            const d = c.getContext('2d').getImageData((40 - 15) * r, (300 - 15) * r, 30 * r, 30 * r).data;
            return d.some((v, i) => i % 4 === 3 && v > 0); }"""
        page.wait_for_function(ring, timeout=1000)
        page.mouse.up()
        self.assertEqual(page.evaluate("document.documentElement.style.getPropertyValue('--stylus')"), up)
        page.wait_for_function(f"!({ring})()", timeout=1000)


class SelectionTests(BrowserCase):
    def test_clicking_around_selects_nothing(self):
        page = self.open(width=1920, height=1060)
        for selector in (".brand", ".press", ".theme-card", ".shell-art", ".meters"):
            with self.subTest(selector=selector):
                box = page.locator(selector).first.bounding_box()
                page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                self.assertEqual(page.evaluate("getSelection().toString()"), "")
                page.keyboard.press("Escape")
        page.mouse.move(20, 20)
        page.mouse.down()
        page.mouse.move(1500, 700, steps=4)
        page.mouse.up()
        self.assertEqual(page.evaluate("getSelection().toString()"), "")

    def test_json_can_still_be_selected(self):
        page = self.open(width=1920, height=1060)
        page.evaluate("setEditing(true)")
        page.click("#toggleJson")
        page.wait_for_selector("#json")
        page.evaluate("document.getElementById('json').select()")
        self.assertGreater(page.evaluate("(() => { const n = document.getElementById('json'); return n.selectionEnd - n.selectionStart; })()"), 100)
        self.assertEqual(page.evaluate("getComputedStyle(document.getElementById('json')).userSelect"), "text")


class PageLoadTests(BrowserCase):
    def check_loaded(self, page):
        self.assertGreater(page.locator("#list .item").count(), 0)
        self.assertEqual(page.locator("#overlay .box").count(), page.evaluate("layout.elements.length"))
        self.assertGreater(page.evaluate("document.querySelector('.console').getBoundingClientRect().width"), 500)

    def test_twenty_loads_in_a_row_all_work(self):
        page = self.open()
        for attempt in range(20):
            with self.subTest(attempt=attempt):
                page.reload()
                wait_ready(page)
                self.check_loaded(page)
        page.wait_for_function("document.getElementById('link').textContent === 'Waiting for the DS…'")
        self.assertRegex(page.text_content("#cpu"), r"^\d+%$")

    def test_localhost_with_animations_on(self):
        page = self.open(motion=True)
        page.goto(harness.url.replace("127.0.0.1", "localhost"))
        wait_ready(page)
        self.check_loaded(page)
        page.evaluate("setEditing(true)")
        page.click("#toggleLayers")
        page.wait_for_selector("#list .item", state="visible")


class SettingsTests(BrowserCase):
    def test_the_shell_tile_switches_between_the_lite_and_the_dsi(self):
        page = self.open()
        self.assertEqual(page.text_content("#shellModelName"), "DS Lite")
        page.click("#shellModel")
        page.wait_for_function("document.querySelector('#shellArt svg').getAttribute('viewBox') === '0 0 531 544'")
        self.assertEqual(page.text_content("#shellModelName"), "DSi")
        self.assertEqual(page.evaluate("localStorage.getItem('shellModel')"), "dsi")
        page.click("#shellModel")
        page.wait_for_function("document.querySelector('#shellArt svg').getAttribute('viewBox') === '0 0 552 575'")

    def test_the_page_art_and_sounds_are_its_own_not_a_theme_s(self):
        page = self.open()
        urls = page.evaluate("performance.getEntriesByType('resource').map(entry => new URL(entry.name).pathname)")
        self.assertIn("/web/ui/sound/select.wav", urls, "Sounds should load with the page, not on the first press")
        self.assertEqual([path for path in urls if path.startswith(("/art/", "/sound/", "/ui/"))], [])
        self.assertIn("svg", page.inner_html("#themeButton"))
        page.click("#themeButton")
        self.assertEqual(page.evaluate("document.documentElement.dataset.theme"), "dark")
        page.click("#themeButton")

    def test_each_theme_card_shows_a_picture_of_it(self):
        page = self.open()
        page.wait_for_function("[...document.querySelectorAll('.theme-card img')].every(i => i.complete && i.naturalWidth === 128)")
        self.assertGreaterEqual(page.locator(".theme-card img").count(), 2)
        self.assertIn("/api/theme.zip?name=Classic", page.get_attribute("#dsThemeExport", "href"))

    def test_colour_changes_can_be_undone(self):
        page = self.open()
        before = page.evaluate("api('/api/themes').then(l => l.themes.Classic)")
        self.addCleanup(page.evaluate, "theme => changeDsTheme({ action: 'colours', theme })", before)
        page.evaluate("colourUndo = []; showColours()")
        self.assertTrue(page.is_disabled("#dsThemeUndo"))
        page.locator("#dsThemeLift").fill("20")
        page.wait_for_function("async () => (await api('/api/themes')).themes.Classic.lift === 20")
        page.keyboard.press("Control+z")
        page.wait_for_function("async before => (await api('/api/themes')).themes.Classic.lift === before", arg=before["lift"])
        self.assertTrue(page.is_disabled("#dsThemeUndo"))

    def test_folded_settings_stay_folded(self):
        page = self.open()
        page.click(".group[data-group=sleep] > summary")
        self.reload(page)
        self.assertFalse(page.evaluate("document.querySelector('.group[data-group=sleep]').open"))
        self.assertTrue(page.evaluate("document.querySelector('.group[data-group=theme]').open"))

    def test_the_preview_dims_with_brightness_and_shows_the_sleep_screen(self):
        page = self.open()
        self.addCleanup(app_brightness, 100)
        dim = "Number(getComputedStyle(document.querySelector('.dim')).opacity)"
        self.assertEqual(page.evaluate(dim), 0)
        page.locator("#brightness").fill("0")
        self.assertAlmostEqual(page.evaluate(dim), .7, places=2)
        page.locator("#brightness").fill("100")
        page.click("#sleepPreview")
        self.assertAlmostEqual(page.evaluate(dim), .49, places=2)       # The sleep screen's 30%
        cat = page.locator(".lcd.top .anim-view img")
        self.assertEqual(cat.count(), 1)
        self.assertIn("sleepy_cat", cat.get_attribute("src"))
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.lcd-frame')).visibility"), "hidden")
        page.keyboard.press("e")
        self.assertTrue(page.evaluate("editing"))
        self.assertFalse(page.evaluate("sleepPreview"), "Editing ends the sleep preview")
        self.assertEqual(page.locator(".anim-view img[src*=sleepy_cat]").count(), 0)
        page.keyboard.press("e")
        self.assertFalse(page.evaluate("editing"))


def app_brightness(level):
    harness.app.set_brightness(level)


class ThemeLayoutTests(BrowserCase):
    def test_each_theme_keeps_its_own_layout(self):
        page = self.open()
        count = page.evaluate("layout.elements.length")
        page.evaluate("""async () => {
          const listing = await api('/api/themes');
          await changeDsTheme({ action: 'save', name: 'Mine', theme: listing.themes[listing.active] });
        }""")
        self.addCleanup(page.evaluate, "changeDsTheme({ action: 'delete', name: 'Mine' })")
        page.evaluate("async () => { remember(); layout.elements.pop(); renderAll(); saveSoon(); }")
        page.evaluate("changeDsTheme({ action: 'use', name: 'Classic' })")
        self.assertEqual(page.evaluate("layout.elements.length"), count)
        self.assertEqual(page.evaluate("undoStack.length"), 0, "Undo shouldn't reach into another theme")
        page.evaluate("changeDsTheme({ action: 'use', name: 'Mine' })")
        self.assertEqual(page.evaluate("layout.elements.length"), count - 1, "The edit before switching was lost")
        page.evaluate("changeDsTheme({ action: 'use', name: 'Classic' })")

    def test_the_sleep_screen_is_set_from_the_theme_menu(self):
        page = self.open()
        page.wait_for_selector("#sleepFile option[value='art:sleep/sleepy_cat.gif']", state="attached")
        self.assertEqual(page.input_value("#sleepFile"), "art:sleep/sleepy_cat.gif")
        page.select_option("#sleepScreen", "bottom")
        page.wait_for_function("async () => (await api('/api/themes')).sleep.screen === 'bottom'")
        self.addCleanup(page.evaluate, "changeDsTheme({ action: 'sleep', sleep: { file: 'art:sleep/sleepy_cat.gif', screen: 'top', brightness: 30 } })")
        page.select_option("#sleepFile", "")
        page.wait_for_function("async () => (await api('/api/themes')).sleep.file === ''")
        self.assertTrue(page.is_disabled("#sleepScreen"))
