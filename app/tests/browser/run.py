#!/usr/bin/env python3
"""Runs the browser tests in installed Chrome. Use `tools/check --browser`.

Needs Windows Python. Playwright lives in a venv outside the repo, made on first use.
This file only uses the standard library, so it can run before that venv exists.
"""
import argparse
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8803
PACKAGES = ["playwright", "pillow", "numpy", "psutil", "pyserial"]
# In run order: browser_polling reads pages that have been open for the whole run.
MODULES = ["browser_preview", "browser_editor", "browser_crop", "browser_page", "browser_polling"]


def skip(reason: str):
    print(f"SKIPPED browser tests: {reason}")
    sys.exit(0)


def venv_path() -> Path:
    override = os.environ.get("DSDASH_TEST_VENV")
    if override:
        return Path(override)
    if "LOCALAPPDATA" not in os.environ:
        skip("they need Windows Python, and LOCALAPPDATA isn't set.")
    return Path(os.environ["LOCALAPPDATA"]) / "dsdash-build" / "test-venv"


def run_in_venv(venv: Path) -> int:
    """Pillow and friends come from the system Python when it has them."""
    python = venv / "Scripts" / "python.exe"
    if not python.exists():
        print(f"Creating {venv}")
        subprocess.run([sys.executable, "-m", "venv", "--system-site-packages", str(venv)],
                       stdin=subprocess.DEVNULL, check=True)
    return subprocess.run([str(python), __file__, *sys.argv[1:]], stdin=subprocess.DEVNULL).returncode


def ensure_playwright():
    if importlib.util.find_spec("playwright"):
        return
    print("Installing playwright. It uses installed Chrome, so there's no browser download.")
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *PACKAGES],
                   stdin=subprocess.DEVNULL)
    importlib.invalidate_caches()
    if not importlib.util.find_spec("playwright"):
        skip(f"playwright isn't installed, and pip couldn't install it into {sys.prefix}.")


def port_is_free() -> bool:
    # Windows lets a second server bind a port in use, so binding wouldn't tell us.
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", PORT)) != 0


class TimedResult(unittest.TextTestResult):
    """Notes each test's time, so a slow one is easy to spot."""
    times = {}

    def startTest(self, test):
        self.began = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        self.times[test.id()] = time.monotonic() - self.began


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-k", dest="patterns", action="append", help="Only run tests matching this")
    parser.add_argument("-v", dest="verbose", action="store_true")
    args = parser.parse_args()

    venv = venv_path()
    if Path(sys.prefix).resolve() != venv.resolve():
        return run_in_venv(venv)
    ensure_playwright()
    if not port_is_free():
        print(f"Port {PORT} is in use. Is another browser test run going?")
        return 1

    started = time.monotonic()
    root = Path(tempfile.mkdtemp(prefix="dsdash-browser-"))
    sys.path.insert(0, str(HERE))
    import harness
    try:
        try:
            harness.start(root, PORT)
        except harness.NoChrome as error:
            skip(f"Chrome wouldn't start: {error}")
        if not harness.HAS_ART:
            print("No app/assets/classic-ds, so checks that need the art will skip.")

        loader = unittest.TestLoader()
        loader.testNamePatterns = [f"*{pattern}*" for pattern in args.patterns or []] or None
        suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in MODULES)
        result = unittest.TextTestRunner(verbosity=2 if args.verbose else 1, stream=sys.stdout,
                                         resultclass=TimedResult).run(suite)
        if args.verbose:
            for name, seconds in sorted(TimedResult.times.items(), key=lambda item: -item[1])[:12]:
                print(f"{seconds:6.2f}s {name}")
    finally:
        harness.stop()
        shutil.rmtree(root, ignore_errors=True)
    print(f"Browser tests took {time.monotonic() - started:.1f}s in all")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
