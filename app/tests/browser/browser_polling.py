"""How often the page polls. This takes real seconds, so it costs the suite none of its own:

one page opens when this module is imported, and sits there while the other tests run.
It records its steady polling, hides itself on a timer, then records the silence.
"""
import harness
from harness import BrowserCase, new_page, wait_ready

HIDE_AFTER_MS = 7000
# A request under way when the tab hides may finish its chain.
SETTLE_MS = 1000
QUIET_MS = 3000

# Runs before the page's scripts, so every fetch gets a timestamp.
WATCH = """
window.fetches = [];
const realFetch = window.fetch;
window.fetch = (url, options) => {
  window.fetches.push({ url: String(url), at: performance.now() });
  return realFetch(url, options);
};
setTimeout(() => {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => window.pretendHidden });
  window.pretendHidden = true;
  window.hiddenAt = performance.now();
  document.dispatchEvent(new Event('visibilitychange'));
}, %d);
""" % HIDE_AFTER_MS
SHOW = """
window.pretendHidden = false;
window.shownAt = performance.now();
document.dispatchEvent(new Event('visibilitychange'));
"""
STEADY = "window.fetches.filter(f => f.at < window.hiddenAt)"
FRAMES = ".filter(f => f.url.includes('/api/frame.png'))"
STATUSES = ".filter(f => f.url.includes('/api/status'))"

context = page = watch = None


def setUpModule():
    # Not at import: other test files set layouts then, and this tab would pick them up.
    global context, page, watch
    context, page, watch = new_page(script=WATCH)
    page.goto(harness.url)
    wait_ready(page)


class PollingTests(BrowserCase):
    @classmethod
    def tearDownClass(cls):
        context.close()

    def setUp(self):
        super().setUp()
        self.problems += watch.problems
        watch.problems = self.problems
        wait = HIDE_AFTER_MS + SETTLE_MS + QUIET_MS + 5000
        page.wait_for_function(f"window.hiddenAt && performance.now() > window.hiddenAt + {SETTLE_MS + QUIET_MS}",
                               timeout=wait)

    def test_one_frame_fetch_a_second(self):
        times = page.evaluate(f"{STEADY}{FRAMES}.map(f => f.at)")
        self.assertGreaterEqual(len(times), 4)
        gaps = [(b - a) / 1000 for a, b in zip(times, times[1:])]
        rate = len(gaps) / ((times[-1] - times[0]) / 1000)
        self.assertGreater(min(gaps[1:]), 0.5, "Frames were fetched too close together")
        self.assertLess(rate, 1.1, "More than one frame fetch a second")
        self.assertGreater(rate, 0.7, "Frames were fetched too rarely")

    def test_status_is_fetched_as_often_as_frames(self):
        frames, statuses = page.evaluate(f"[{STEADY}{FRAMES}.length, {STEADY}{STATUSES}.length]")
        self.assertLessEqual(abs(frames - statuses), 2)

    def test_hidden_tab_stops_polling_and_comes_back(self):
        late = page.evaluate(f"window.fetches.filter(f => f.at > window.hiddenAt + {SETTLE_MS}).map(f => f.url)")
        self.assertEqual(late, [], "A hidden tab kept polling")

        page.evaluate(SHOW)
        page.wait_for_function(f"window.fetches{FRAMES}.some(f => f.at >= window.shownAt)", timeout=3000)
