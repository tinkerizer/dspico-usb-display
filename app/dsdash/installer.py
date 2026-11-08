"""Per-user install: no admin rights, and everything it adds is removed by uninstall."""
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .version import VERSION

log = logging.getLogger(__name__)

APP_NAME = "DS Display"
EXE_NAME = "DS Display.exe"
INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "Programs" / "DSDisplay"
INSTALLED_EXE = INSTALL_DIR / EXE_NAME
START_MENU = Path(os.environ.get("APPDATA", ".")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
SHORTCUT = START_MENU / f"{APP_NAME}.lnk"

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DSDisplay"
NO_WINDOW = 0x08000000
COPY_ATTEMPTS = 30
COPY_RETRY_SECONDS = .5


def is_installed_copy() -> bool:
    return Path(sys.executable).resolve() == INSTALLED_EXE.resolve()


def stop_other_copies():
    """Stops a running copy, so its file can be replaced. Spares this process."""
    subprocess.run(
        ["taskkill", "/F", "/IM", EXE_NAME, "/FI", f"PID ne {os.getpid()}", "/FI", f"PID ne {os.getppid()}"],
        creationflags=NO_WINDOW, capture_output=True)


def autostart_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{INSTALLED_EXE}" --background')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def _create_shortcut():
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:DS_LINK); "
        "$s.TargetPath = $env:DS_TARGET; $s.Description = 'DS Display'; $s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, creationflags=NO_WINDOW,
                   env={**os.environ, "DS_LINK": str(SHORTCUT), "DS_TARGET": str(INSTALLED_EXE)})


def _register_uninstall():
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        values = {
            "DisplayName": APP_NAME,
            "DisplayVersion": VERSION,
            "Publisher": "tinkerizer",
            "DisplayIcon": str(INSTALLED_EXE),
            "InstallLocation": str(INSTALL_DIR),
            "UninstallString": f'"{INSTALLED_EXE}" --uninstall',
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def _replace_exe():
    """Windows can keep a stopped copy's file locked for a moment after taskkill returns."""
    for attempt in range(COPY_ATTEMPTS):
        try:
            shutil.copy2(sys.executable, INSTALLED_EXE)
            return
        except PermissionError:
            if attempt == COPY_ATTEMPTS - 1:
                raise
            time.sleep(COPY_RETRY_SECONDS)


def install():
    stop_other_copies()
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    _replace_exe()
    _create_shortcut()
    _register_uninstall()
    set_autostart(True)
    log.info("Installed to %s", INSTALL_DIR)


def uninstall():
    """Removes the program. Layouts and uploads stay, in case of a reinstall."""
    import winreg

    stop_other_copies()
    set_autostart(False)
    SHORTCUT.unlink(missing_ok=True)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass

    # A running exe can't delete itself, so a detached shell does it just after exit.
    subprocess.Popen(f'cmd /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "{INSTALL_DIR}"',
                     creationflags=NO_WINDOW, cwd=os.environ.get("TEMP"), close_fds=True)
    log.info("Uninstalled")
