"""One server and one Chrome for every browser test, all on a temporary copy of the app.

Nothing here may reach the DS or the user's data: the app runs from the copy, its
device threads never start, and start() refuses to go on if the layout path is outside it.
"""
import logging
import re
import shutil
import sys
import threading
import unittest
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import Error as PlaywrightError, sync_playwright

REPO = Path(__file__).resolve().parents[3]
W, H, SEAM, HINGE = 256, 384, 192, 101
SCALE = 4                               # Of blocks.png, the art for the crop tests.
ANIMATION_COLOUR = (255, 0, 0)
HAS_ART = (REPO / "app" / "assets" / "themes" / "classic").is_dir()
NEEDS_ART = re.compile(r"/art/|art%3A")   # Requests that only 404 because the art is missing.

# Waits for what start() in app.js draws, and for the shell and the first frame.
READY = """() => document.querySelector('#list .item') && document.querySelector('#shellArt svg')
  && [...document.querySelectorAll('.lcd-frame')].every(frame => frame.complete && frame.naturalWidth === 256)"""
RESET_PATH = "/web/arrow.svg"           # Small, and on the app's origin, so it can reach storage.
# This PC has no GPU for Chrome to use, so its GPU process only costs time: about 15% of a run.
CHROME_ARGS = ["--disable-gpu"]
NEXT_PAINT = "new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)))"

url = ""
app = None
layouts = None
browser = None
_playwright = None
_pages = {}


class NoChrome(Exception):
    pass


def _copy_app(root: Path):
    """The local folder is left out, so the user's layout and uploads can't get in."""
    source = REPO / "app"
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(source / "dsdash", root / "app" / "dsdash", ignore=ignore)
    shutil.copytree(source / "assets" / "fonts", root / "app" / "assets" / "fonts")
    shutil.copytree(source / "assets" / "templates", root / "app" / "assets" / "templates")
    if HAS_ART:
        shutil.copytree(source / "assets" / "themes", root / "app" / "assets" / "themes")
    (root / "tools").mkdir()
    shutil.copy2(REPO / "tools" / "dsctl.py", root / "tools")
    host = root / "libs" / "dsupdate" / "host"
    host.mkdir(parents=True)
    shutil.copy2(REPO / "libs" / "dsupdate" / "host" / "dsupdate.py", host)


def _write_fixtures(local: Path):
    """Art made here, so these tests don't depend on the git-ignored files."""
    local.mkdir(parents=True, exist_ok=True)
    colours = np.random.default_rng(7).integers(0, 255, (12, 16, 3), dtype=np.uint8)
    Image.fromarray(colours.repeat(SCALE, 0).repeat(SCALE, 1)).save(local / "blocks.png")
    frames = [Image.new("RGB", (40, 36), ANIMATION_COLOUR) for _ in range(2)]
    frames[1].putpixel((0, 0), (0, 0, 255))
    frames[0].save(local / "cloud.gif", save_all=True, append_images=frames[1:], duration=100, loop=0)


def _refuse_ports(*args, **kwargs):
    raise AssertionError("A browser test tried to open a serial port")


def start(root: Path, port: int):
    global url, app, layouts, browser, _playwright
    # The source is on a slow share, so this overlaps with starting Chrome.
    copying = threading.Thread(target=_copy_app, args=(root,))
    copying.start()
    _playwright = sync_playwright().start()
    try:
        browser = _playwright.chromium.launch(channel="chrome", headless=True, args=CHROME_ARGS)
    except PlaywrightError as error:
        raise NoChrome(str(error).splitlines()[0]) from error
    finally:
        copying.join()
    sys.path.insert(0, str(root / "app"))

    import serial
    serial.Serial = _refuse_ports
    import dsdash
    from dsdash import layout as layouts_module, server
    from dsdash.app import App
    from dsdash.device import DsDevice
    from dsdash.firmware import FirmwareKeeper

    layouts = layouts_module
    for path in (Path(dsdash.__file__), layouts.LOCAL_DIR):
        if root.resolve() not in path.resolve().parents:
            raise AssertionError(f"{path} is outside the temporary copy {root}")
    DsDevice.start = lambda self: None
    FirmwareKeeper.start = lambda self: None
    logging.disable(logging.WARNING)

    app = App()
    _write_fixtures(app.themes.uploads_dir())
    app.set_layout(test_layout())
    app.start()
    http = server.create_server(app, port)
    threading.Thread(target=http.serve_forever, name="browser-test-server", daemon=True).start()
    url = f"http://127.0.0.1:{port}"


def real_scale_page(width: int, height: int, scale: int, frame: bytes):
    """Chrome with a true scale factor, as on a real high DPI screen. Emulated ones lay out
    in CSS pixels and scale up after, so a half CSS pixel snaps to a whole one first."""
    real = _playwright.chromium.launch(channel="chrome", headless=True, args=[*CHROME_ARGS,
        f"--force-device-scale-factor={scale}", f"--window-size={width},{height}"])
    context = real.new_context(no_viewport=True, reduced_motion="reduce")
    prepare(context, frame)
    return real, context.new_page()


def set_window(page, width: int, height: int):
    """Resizes a real_scale_page, which has no emulated viewport to change."""
    before = page.evaluate("[innerWidth, innerHeight]")
    cdp = page.context.new_cdp_session(page)
    window = cdp.send("Browser.getWindowForTarget")["windowId"]
    cdp.send("Browser.setWindowBounds", {"windowId": window, "bounds": {"width": width, "height": height}})
    page.wait_for_function("([w, h]) => innerWidth !== w || innerHeight !== h", arg=before)
    page.evaluate(NEXT_PAINT)


def stop():
    if browser:
        browser.close()
    if _playwright:
        _playwright.stop()


def test_layout() -> dict:
    """default_layout() as it stands, plus the art for the crop tests. Never the user's."""
    layout = layouts.default_layout()
    layout["elements"].append(image_element("art", 150, 200, 64, 48))
    return layout


def image_element(id_: str, x: int, y: int, w: int, h: int, **props) -> dict:
    return {"id": id_, "type": "image", "x": x, "y": y, "w": w, "h": h,
            "props": {"file": "art:uploads/blocks.png", **props}}


def changed(update) -> dict:
    """The test layout, after a function has edited its elements by id."""
    layout = test_layout()
    update({element["id"]: element for element in layout["elements"]})
    return layout


def pattern_frame() -> bytes:
    """Every DS pixel differs from its neighbours, so any resampling shows."""
    pixels = np.random.default_rng(11).integers(0, 255, (H, W, 3), dtype=np.uint8)
    out = BytesIO()
    Image.fromarray(pixels).save(out, "PNG")
    return out.getvalue()


def black_frame() -> bytes:
    out = BytesIO()
    Image.new("RGB", (W, H)).save(out, "PNG")
    return out.getvalue()


def decode(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(BytesIO(png)).convert("RGB"))


class Watch:
    """Collects everything on a page that should never happen, into the current test's list."""

    def __init__(self, page):
        self.problems = []
        page.on("pageerror", lambda error: self.problems.append(f"Page error: {error}"))
        page.on("console", self._console)
        page.on("response", self._response)

    def _console(self, message):
        source = message.location.get("url", "")
        if message.type != "error" or source.endswith("/favicon.ico"):  # Chrome asks by itself. There isn't one.
            return
        if HAS_ART or "Failed to load resource" not in message.text:
            self.problems.append(f"Console error: {message.text} at {source}")

    def _response(self, response):
        if response.status >= 400 and "favicon" not in response.url and (HAS_ART or not NEEDS_ART.search(response.url)):
            self.problems.append(f"{response.status} from {response.url}")


def prepare(context, frame=None):
    if frame:
        context.route("**/api/frame.png", lambda route: route.fulfill(body=frame, content_type="image/png"))
    if not HAS_ART:
        # These have no fallback in the server, which would just drop the connection.
        context.route("**/ui/*", lambda route: route.fulfill(status=204))
        context.route("**/sound/*", lambda route: route.fulfill(status=204))


def new_page(width=1600, height=1000, dpr=1, motion=False, frame=None, script=None):
    """A new profile, which costs a new renderer. Returns the context, page and Watch."""
    context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=dpr,
                                  reduced_motion="no-preference" if motion else "reduce")
    prepare(context, frame)
    if script:
        context.add_init_script(script)
    page = context.new_page()
    return context, page, Watch(page)


def wait_ready(page):
    page.wait_for_function(READY)


class BrowserCase(unittest.TestCase):
    # Editing tests only need a known layout, not a new document, and a page load is most of
    # what they'd cost. Tests about loading, storage or sizes must leave this off.
    soft_reset = False
    editing = False     # True opens the screens editor, rather than the shell preview.

    @classmethod
    def tearDownClass(cls):
        # Pages left open keep polling and repainting, which slows down everything else.
        for context, _, _ in _pages.values():
            context.close()
        _pages.clear()

    def setUp(self):
        self.problems = []

    def tearDown(self):
        self.assertEqual(self.problems, [])

    def open(self, layout=None, width=1600, height=1000, dpr=1, motion=False, frame=None, stored=None):
        """A page in a known state. Pages are reused, as making one takes longer than most tests."""
        key = dpr, motion, frame, self.soft_reset and type(self)
        if key not in _pages:
            _pages[key] = new_page(width, height, dpr, motion, frame)
        _, page, watch = _pages[key]
        watch.problems = self.problems

        wanted = {"width": width, "height": height}
        if self.soft_reset and not stored and page.url == url + "/":
            if page.viewport_size != wanted:
                page.set_viewport_size(wanted)
                page.wait_for_function("([w, h]) => innerWidth === w && innerHeight === h", arg=[width, height])
            return self.set_editing(self.reset_in_place(page, layout))

        page.mouse.up()
        page.mouse.move(0, 0)
        if page.viewport_size != wanted:
            page.set_viewport_size(wanted)
        # Leaving the app drops its timers, so an old save can't undo the layout set below.
        page.goto(url + RESET_PATH)
        page.evaluate("""stored => {
          localStorage.clear();
          sessionStorage.clear();
          for (const [key, value] of Object.entries(stored)) localStorage.setItem(key, value);
        }""", stored or {})
        app.set_layout(layout or test_layout())
        page.goto(url)
        wait_ready(page)
        return self.set_editing(page)

    def set_editing(self, page):
        page.evaluate("on => setEditing(on)", self.editing)
        return page

    def reset_in_place(self, page, layout):
        page.evaluate("""async () => {
          clearTimeout(saveTimer);
          while (saving) await new Promise(done => setTimeout(done, 5));
        }""")
        clean, saved_revision = app.set_layout(layout or test_layout())
        page.evaluate("""([clean, savedRevision]) => {
          layout = clean;
          revision = savedRevision;
          selectedId = null;
          undoStack = [];
          redoStack = [];
          keepBoxShape = jsonDirty = false;
          collapsedLayers.clear();
          localStorage.clear();
          closeMenu();
          updateHistoryButtons();
          renderAll();
        }""", [clean, saved_revision])
        return page

    def reload(self, page):
        page.reload()
        wait_ready(page)
        self.set_editing(page)

    # The page's own state. Its top-level `let`s are visible to evaluate().

    def element(self, page, id_: str) -> dict:
        return page.evaluate("id => layout.elements.find(e => e.id === id)", id_)

    def geometry(self, page, id_: str) -> tuple:
        e = self.element(page, id_)
        return e["x"], e["y"], e["w"], e["h"]

    def select(self, page, id_: str):
        page.evaluate("id => select(id)", id_)

    def wait_saved(self, page, check):
        """Waits for the server to hold a layout that passes the check."""
        for _ in range(300):
            if check({e["id"]: e for e in app.layout["elements"]}):
                return
            page.wait_for_timeout(10)
        self.fail("The server never got the change")

    # Pointer positions on the preview

    def unit(self, page) -> float:
        return page.evaluate("document.getElementById('screens').getBoundingClientRect().width") / W

    def view_point(self, page, x: float, row: float) -> tuple:
        """A position on the preview, in DS pixels, counting the hinge's rows."""
        left, top, width = page.evaluate(
            "(({left, top, width}) => [left, top, width])(document.getElementById('screens').getBoundingClientRect())")
        unit = width / W
        return left + x * unit, top + row * unit

    def ds_point(self, page, x: float, y: float) -> tuple:
        """A position on the DS itself, which skips the hinge."""
        return self.view_point(page, x, y + page.evaluate("HINGE") if y >= SEAM else y)

    def press(self, page, point: tuple):
        self.addCleanup(page.mouse.up)      # A failed test mustn't leave the next one mid-drag.
        page.mouse.move(*point)
        page.mouse.down()

    def drag(self, page, start: tuple, end: tuple):
        self.press(page, start)
        page.mouse.move(*end, steps=2)
        page.mouse.up()
