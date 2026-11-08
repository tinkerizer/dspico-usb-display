#!/usr/bin/env python3
"""Builds "DS Display Setup.exe". Run with Windows Python; the result lands in app/dist.

Add --update to upgrade the bundled packages, which is skipped to keep builds quick.

The art and your GIFs get bundled, so the exe is for your own use. Don't publish it.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent
WORK = Path(os.environ["LOCALAPPDATA"]) / "dsdash-build"
VENV_PYTHON = WORK / "venv" / "Scripts" / "python.exe"
PACKAGES = ["pyinstaller", "pillow", "numpy", "pyserial", "psutil", "pystray"]


def run(*command):
    subprocess.run([str(part) for part in command], check=True)


def main():
    new = not VENV_PYTHON.exists()
    if new:
        run(sys.executable, "-m", "venv", WORK / "venv")
    if new or "--update" in sys.argv:
        run(VENV_PYTHON, "-m", "pip", "install", "--quiet", "--upgrade", *PACKAGES)

    # PyInstaller works best from a normal local path, not a WSL share.
    source = WORK / "source"
    shutil.rmtree(source, ignore_errors=True)
    source.mkdir(parents=True)
    shutil.copytree(APP / "dsdash", source / "dsdash", ignore=shutil.ignore_patterns("__pycache__"))
    version = (APP.parent / "VERSION").read_text().strip()
    (source / "dsdash" / "version.py").write_text(f"VERSION = {version!r}\n")
    shutil.copy2(APP / "desktop.py", source)
    shutil.copytree(APP / "assets", source / "assets")

    # Dev feature: the app keeps the DS on this build. See dsdash/firmware.py.
    rom = APP.parent / "ds" / "usb-display.nds"
    if not rom.exists():
        sys.exit("Build the DS app first: make -C ds")
    shutil.copy2(rom, source / "assets")
    shutil.copy2(APP.parent / "tools" / "dsctl.py", source)
    shutil.copy2(APP.parent / "libs" / "dsupdate" / "host" / "dsupdate.py", source)

    subprocess.run([str(VENV_PYTHON), "-c", "from dsdash.icon import save_ico; save_ico('icon.ico')"],
                   check=True, cwd=source)

    subprocess.run([
        str(VENV_PYTHON), "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
        "--name", "DS Display Setup", "--icon", str(source / "icon.ico"),
        "--add-data", f"{source / 'assets'};assets", "--add-data", f"{source / 'dsdash' / 'web'};dsdash/web",
        "--hidden-import", "pystray._win32", "--hidden-import", "dsctl", "--hidden-import", "dsupdate", "--collect-submodules", "dsdash.elements",
        "--distpath", str(WORK / "dist"), "--workpath", str(WORK / "pyi"), "--specpath", str(WORK),
        "desktop.py",
    ], check=True, cwd=source)

    target = APP / "dist"
    target.mkdir(exist_ok=True)
    shutil.copy2(WORK / "dist" / "DS Display Setup.exe", target)
    print(f"Built {target / 'DS Display Setup.exe'}")


if __name__ == "__main__":
    main()
