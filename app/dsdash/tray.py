"""The taskbar icon: status at a glance, and a menu for the common actions."""
import logging
import threading
import webbrowser

import pystray
from pystray import Menu, MenuItem

from . import installer
from .app import App
from .icon import draw_icon

log = logging.getLogger(__name__)

CONNECTED = (40, 180, 70, 255)
WAITING = (200, 150, 30, 255)
BRIGHTNESS_LEVELS = (100, 75, 50, 25)


class Tray:
    def __init__(self, app: App, url: str, can_install: bool):
        self.app = app
        self.url = url
        self.can_install = can_install
        self._stop = threading.Event()
        self.icon = pystray.Icon("DSDisplay", draw_icon(64, WAITING), "DS Display: waiting for the DS", self._menu())

    def _status_text(self, item=None) -> str:
        status = self.app.device.status
        return f"Connected on {status.port}" if status.connected else "Waiting for the DS…"

    def _brightness_item(self, level: int) -> MenuItem:
        return MenuItem(f"{level}%", lambda: self.app.set_brightness(level),
                        checked=lambda item: self.app.brightness == level, radio=True)

    def _menu(self) -> Menu:
        items = [
            MenuItem("Open editor", self.open_editor, default=True),
            MenuItem(self._status_text, None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Brightness", Menu(*[self._brightness_item(level) for level in BRIGHTNESS_LEVELS])),
        ]
        if self.can_install:
            items += [
                MenuItem("Start with Windows", self._toggle_autostart,
                         checked=lambda item: installer.autostart_enabled()),
                MenuItem("Uninstall", self._uninstall),
            ]
        items += [Menu.SEPARATOR, MenuItem("Quit", self.quit)]
        return Menu(*items)

    def open_editor(self):
        webbrowser.open(self.url)

    def _toggle_autostart(self):
        installer.set_autostart(not installer.autostart_enabled())

    def _uninstall(self):
        installer.uninstall()
        self.quit()

    def quit(self):
        self._stop.set()
        self.app.stop()
        self.icon.stop()

    def _watch_status(self):
        """Keeps the icon and its tooltip in step with the DS connection."""
        shown = None
        while not self._stop.wait(1):
            connected = self.app.device.status.connected
            if connected != shown:
                shown = connected
                self.icon.icon = draw_icon(64, CONNECTED if connected else WAITING)
                self.icon.title = f"DS Display: {self._status_text()}"
                self.icon.update_menu()

    def run(self):
        threading.Thread(target=self._watch_status, name="ds-tray", daemon=True).start()
        self.icon.run()
