"""Windows entry point. Run from anywhere it installs itself; installed, it runs in the tray."""
import argparse
import ctypes
import logging
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dsdash import installer, layout

PORT = 8765
URL = f"http://127.0.0.1:{PORT}"


def message(text: str):
    ctypes.windll.user32.MessageBoxW(None, text, "DS Display", 0x40)


def configure_logging():
    layout.APP_DATA.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=layout.APP_DATA / "dsdisplay.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")


def run_app(open_browser: bool):
    from dsdash.app import App
    from dsdash.server import create_server
    from dsdash.tray import Tray

    app = App()
    try:
        server = create_server(app, PORT)
    except OSError:
        # Already running, so this launch just means "show me the editor".
        webbrowser.open(URL)
        return

    app.start()
    threading.Thread(target=server.serve_forever, name="ds-web", daemon=True).start()
    tray = Tray(app, URL, can_install=layout.FROZEN)
    logging.info("Running at %s", URL)
    if open_browser:
        tray.open_editor()
    tray.run()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--background", action="store_true", help="Start without opening the browser")
    parser.add_argument("--quiet", action="store_true", help="Install or uninstall without messages")
    args = parser.parse_args()
    configure_logging()

    try:
        if args.uninstall:
            installer.uninstall()
            if not args.quiet:
                message("DS Display has been removed. Your layouts are kept in case you reinstall.")
        elif layout.FROZEN and not installer.is_installed_copy():
            installer.install()
            subprocess.Popen([str(installer.INSTALLED_EXE)] + (["--background"] if args.quiet else []),
                             close_fds=True)
            if not args.quiet:
                message("DS Display is installed. It will start with Windows, and lives in the taskbar.")
        else:
            run_app(open_browser=not args.background)
    except Exception:
        logging.exception("DS Display failed")
        raise


if __name__ == "__main__":
    main()
