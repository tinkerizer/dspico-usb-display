"""The app's version, from VERSION at the repo root. build_windows.py writes it in here for the installer."""
from pathlib import Path

try:
    VERSION = (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
except OSError:
    VERSION = "unknown"
