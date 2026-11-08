#!/usr/bin/env python3
"""Measures display throughput on the DS. Needs the display port to itself, so quit the PC app first.

From WSL: python.exe "$(wslpath -w tools/ds_bench.py)"
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dsctl

PACKET_MAGIC = 0xD5
PACKET_RECT_RAW = 5


def rect_packet(width, height, pixels):
    payload = struct.pack("<4H", 0, 0, width, height) + pixels
    padding = -len(payload) % 4
    return struct.pack("<BBHI", PACKET_MAGIC, PACKET_RECT_RAW, 0, len(payload)) + payload + bytes(padding)


def find_display_port():
    from serial.tools.list_ports import comports

    for port in comports():
        if port.vid == dsctl.USB_VID and port.pid == dsctl.USB_PID and (dsctl.interface_number(port.location) or 0) == 0:
            return port.device
    raise dsctl.DsError("No DS display port found")


def wait_until_drained(link, target_bytes, timeout=60):
    """Waits for the DS to receive everything and draw every chunk."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = link.ping()
        if status["usb_bytes"] >= target_bytes and status["ring_head"] == status["ring_tail"]:
            return
        time.sleep(0.002)
    raise dsctl.DsError("DS did not finish the data")


def run_case(display, link, name, width, height, count):
    pixels = os.urandom(width * height * 2)
    packet = rect_packet(width, height, pixels)
    start_bytes = link.ping()["usb_bytes"]

    started = time.perf_counter()
    for _ in range(count):
        display.write(packet)
    wait_until_drained(link, start_bytes + len(packet) * count)
    elapsed = time.perf_counter() - started

    total = len(packet) * count
    print(f"{name:22s} {count:5d} x {len(packet):6d} B   {total / elapsed / 1024:7.1f} KB/s   "
          f"{count / elapsed:7.1f} updates/s   {elapsed / count * 1000:7.2f} ms each")


def main():
    import serial

    with serial.Serial(find_display_port(), 115200, timeout=2, write_timeout=30) as display, \
            dsctl.open_dev_port() as dev:
        link = dsctl.Link(dev, on_log=lambda text: None)
        time.sleep(0.5)
        print(f"Build {link.ping()['build']}")
        run_case(display, link, "Full frame 256x384", 256, 384, 10)
        run_case(display, link, "One screen 256x192", 256, 192, 20)
        run_case(display, link, "Graph 110x28", 110, 28, 100)
        run_case(display, link, "Text 56x12", 56, 12, 300)
        run_case(display, link, "Tiny 8x8", 8, 8, 500)


if __name__ == "__main__":
    main()
