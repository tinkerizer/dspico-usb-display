"""How the page keeps up to date. This takes real seconds, so it costs the suite none of its own:

one page opens when this module is imported, and sits there while the other tests run.
It records what arrives, hides itself on a timer, then records the silence.
"""
import harness
from harness import BrowserCase, new_page, wait_ready

HIDE_AFTER_MS = 7000
# A request under way when the tab hides may finish its chain.
SETTLE_MS = 1000
QUIET_MS = 3000

# Runs before the page's scripts, so every fetch and every pushed status gets a timestamp.
WATCH = """
window.fetches = [];
window.pushed = [];
window.streams = { opened: 0, closed: 0 };
const realFetch = window.fetch;
window.fetch = (url, options) => {
  window.fetches.push({ url: String(url), at: performance.now() });
  return realFetch(url, options);
};
window.EventSource = class extends EventSource {
  constructor(url) {
    super(url);
    window.streams.opened++;
    this.addEventListener('message', () => window.pushed.push(performance.now()));
  }
  close() { window.streams.closed++; super.close(); }
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

    def test_a_frame_is_fetched_when_the_picture_changes(self):
        """The clock changes it every second. Other tests' edits, going on meanwhile, add a few more."""
        times = page.evaluate(f"{STEADY}{FRAMES}.map(f => f.at)")
        self.assertGreaterEqual(len(times), 4)
        rate = (len(times) - 1) / ((times[-1] - times[0]) / 1000)
        self.assertLess(rate, 3, "Frames were fetched far more often than the picture changes")
        self.assertGreater(rate, 0.7, "Frames were fetched too rarely")

    def test_the_status_is_pushed_not_asked_for(self):
        statuses, pushed = page.evaluate(f"[{STEADY}{STATUSES}.length, window.pushed.filter(at => at < window.hiddenAt).length]")
        self.assertEqual(statuses, 0, "The page still polls for its status")
        self.assertGreaterEqual(pushed, 4)

    def test_hidden_tab_stops_listening_and_comes_back(self):
        late = page.evaluate(f"window.fetches.filter(f => f.at > window.hiddenAt + {SETTLE_MS}).map(f => f.url)")
        self.assertEqual(late, [], "A hidden tab kept fetching")
        self.assertEqual(page.evaluate("window.pushed.filter(at => at > window.hiddenAt + 100)"), [], "A hidden tab kept listening")
        self.assertEqual(page.evaluate("window.streams"), {"opened": 1, "closed": 1})

        page.evaluate(SHOW)
        page.wait_for_function(f"window.fetches{FRAMES}.some(f => f.at >= window.shownAt)", timeout=3000)
        self.assertEqual(page.evaluate("window.streams.opened"), 2)
