#!/usr/bin/env python3
"""On-hardware display test: draws random rects and compares a screenshot pixel for pixel.

Needs the DS running and the display port free, so quit the PC app first.
From WSL: python.exe "$(wslpath -w tools/test_ds_hw.py)"
"""
import os
import random
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ds_bench
import dsctl

WIDTH, HEIGHT = dsctl.SCREEN_WIDTH, dsctl.SCREEN_HEIGHT
PACKET_RECT_RLE = 6

# (x, y, width, height): alignment cases, the DMA threshold, and both screens.
RECTS = [
    (0, 0, 256, 384),
    (1, 1, 111, 28),
    (8, 124, 111, 28),
    (137, 156, 111, 28),
    (3, 50, 15, 9),
    (5, 60, 16, 9),
    (7, 70, 17, 9),
    (255, 383, 1, 1),
    (0, 383, 256, 1),
    (2, 185, 100, 15),     # Crosses from the top screen to the bottom one
    (101, 180, 33, 30),
    (200, 300, 56, 84),
]


def rle_tokens(pixels):
    """Simple encoder that exercises both token types."""
    out = bytearray()
    index = 0
    while index < len(pixels):
        run = 1
        while index + run < len(pixels) and pixels[index + run] == pixels[index]:
            run += 1
        if run >= 3:
            out += struct.pack("<HH", 0x8000 | (run - 1), pixels[index])
            index += run
        else:
            end = min(index + 37, len(pixels))
            out += struct.pack(f"<H{end - index}H", end - index - 1, *pixels[index:end])
            index = end
    return bytes(out)


def main():
    import serial

    rng = random.Random(1234)
    expected = [0x8000] * (WIDTH * HEIGHT)
    with serial.Serial(ds_bench.find_display_port(), 115200, timeout=2, write_timeout=30) as display, \
            dsctl.open_dev_port() as dev:
        link = dsctl.Link(dev, on_log=lambda text: None)
        time.sleep(0.5)     # The DS clears the screens when the port opens

        for rounds in range(3):
            for x, y, width, height in RECTS:
                use_rle = rounds == 1
                pixels = [0x8000 | rng.getrandbits(15) for _ in range(width * height)]
                if use_rle:
                    # Flat stretches plus noise, like UI graphics.
                    colors = [0x8000 | rng.getrandbits(15) for _ in range(4)]
                    pixels = [rng.choice(colors) if i % 97 < 11 else colors[(i // 97) % 4]
                              for i in range(width * height)]
                body = rle_tokens(pixels) if use_rle else struct.pack(f"<{len(pixels)}H", *pixels)
                payload = struct.pack("<4H", x, y, width, height) + body
                packet_type = PACKET_RECT_RLE if use_rle else ds_bench.PACKET_RECT_RAW
                packet = struct.pack("<BBHI", ds_bench.PACKET_MAGIC, packet_type, 0, len(payload))
                display.write(packet + payload + bytes(-len(payload) % 4))
                for row in range(height):
                    start = (y + row) * WIDTH + x
                    expected[start:start + width] = pixels[row * width:(row + 1) * width]

            start_bytes = link.ping()["usb_bytes"]
            ds_bench.wait_until_drained(link, start_bytes)
            time.sleep(0.1)
            actual = struct.unpack(f"<{WIDTH * HEIGHT}H", link.request(dsctl.OP_SCREENSHOT))
            # The heartbeat squares are drawn over the top-right corner.
            wrong = [i for i in range(WIDTH * HEIGHT)
                     if actual[i] != expected[i] and not (i // WIDTH < 3 and i % WIDTH >= 240)]
            if wrong:
                first = wrong[0]
                sys.exit(f"Round {rounds}: {len(wrong)} wrong pixels, first at "
                         f"({first % WIDTH}, {first // WIDTH}): {actual[first]:#06x} != {expected[first]:#06x}")
            print(f"Round {rounds} ({'RLE' if rounds == 1 else 'raw'}): {len(RECTS)} rects match, pixel for pixel")


if __name__ == "__main__":
    main()
