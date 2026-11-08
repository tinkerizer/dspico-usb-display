#!/usr/bin/env python3
"""Deploy to and debug the DS over USB, using the dev port in ds/common/DebugProtocol.h.

  push [file.nds]        Upload, reboot into it, and confirm it is running
  install [file.nds]     Replace the copy on the SD card, so it survives a power cycle
  drive                  Lend the SD card to this PC as a drive until it's ejected
  ping                   Check the DS is alive and show its counters
  log                    Stream DS log output until Ctrl+C
  shot [out.png]         Save both screens as a PNG
  peek ADDRESS LENGTH    Hex dump memory
  poke ADDRESS HEXBYTES  Write memory

From WSL, run through tools/ds so the command uses Windows Python.
"""
import argparse
import re
import struct
import sys
import time
import zlib
from pathlib import Path

USB_VID = 0x1209
USB_PID = 0xDD01

FRAME = struct.Struct("<HBBI")
FRAME_MAGIC = 0x4244
PROTOCOL_VERSION = 3

OP_PING, OP_READ, OP_WRITE, OP_SCREENSHOT, OP_BOOT, OP_SD_DRIVE, OP_LOG = 1, 2, 3, 4, 5, 6, 0x80
STATUS_TEXT = {1: "bad request", 2: "CRC mismatch", 3: "ARM9 not responding", 4: "no SD card or driver"}

STAGING_BASE = 0x02200000
STAGING_SIZE = 0x00140000
ARM9_RAM_MIN = 0x02000000
ARM9_RAM_END = 0x02100000
ARM7_RAM_MIN = 0x02380000
ARM7_RAM_END = 0x023F0000

SCREEN_WIDTH, SCREEN_HEIGHT = 256, 384
WRITE_CHUNK = 32 * 1024
USB_PACKET_SIZE = 64
REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    import dsupdate
except ImportError:     # Running from the repo. The packaged app bundles it.
    sys.path.insert(0, str(REPO_ROOT / "libs" / "dsupdate" / "host"))
    import dsupdate


class DsError(Exception):
    pass


def interface_number(location):
    match = re.search(r"\.(\d+)$", location or "")
    return int(match.group(1)) if match else None


def find_dev_port(ports):
    """Returns the DS dev port, which is any serial interface other than 0."""
    for port in ports:
        if port.vid == USB_VID and port.pid == USB_PID and (interface_number(port.location) or 0) != 0:
            return port.device
    return None


def open_dev_port(timeout=15.0):
    import serial
    from serial.tools.list_ports import comports

    deadline = time.monotonic() + timeout
    while True:
        device = find_dev_port(comports())
        if device:
            try:
                return serial.Serial(device, baudrate=115200, timeout=5, write_timeout=5)
            except serial.SerialException:
                pass  # Still enumerating, or owned by another process
        if time.monotonic() >= deadline:
            raise DsError("No DS dev port found. Is a build with the dev port running and plugged in?")
        time.sleep(0.2)


class Link:
    def __init__(self, stream, on_log=None):
        self.stream = stream
        self.on_log = on_log or (lambda text: print(text, end="", flush=True))

    def _read_exact(self, length):
        data = bytearray()
        while len(data) < length:
            part = self.stream.read(length - len(data))
            if not part:
                raise DsError(f"Timed out with {length - len(data)} of {length} bytes outstanding")
            data += part
        return bytes(data)

    def read_frame(self):
        magic, op, status, length = FRAME.unpack(self._read_exact(FRAME.size))
        if magic != FRAME_MAGIC:
            raise DsError(f"Bad frame magic {magic:#06x}")
        return op, status, self._read_exact(length)

    def request(self, op, payload=b""):
        self.stream.write(FRAME.pack(FRAME_MAGIC, op, 0, len(payload)) + payload)
        while True:
            reply_op, status, data = self.read_frame()
            if reply_op == OP_LOG:
                self.on_log(data.decode("utf-8", "replace"))
            elif reply_op != op:
                raise DsError(f"Expected reply to op {op}, got op {reply_op}")
            elif status != 0:
                raise DsError(STATUS_TEXT.get(status, f"status {status}"))
            else:
                return data

    def ping(self):
        version, boot_crc, usb_bytes, packets, ring_head, ring_tail, build = struct.unpack("<7I", self.request(OP_PING))
        if version != PROTOCOL_VERSION:
            raise DsError(f"DS speaks protocol {version}, this tool speaks {PROTOCOL_VERSION}")
        return {"build": build, "boot_crc": boot_crc, "usb_bytes": usb_bytes, "packets": packets,
                "ring_head": ring_head, "ring_tail": ring_tail}

    def write_memory(self, address, data):
        offset = 0
        while offset < len(data):
            part = data[offset:offset + WRITE_CHUNK]
            # A USB transfer only ends early on a short packet, so a frame filling its
            # last packet exactly would sit in the DS's buffer waiting for more.
            if (FRAME.size + 4 + len(part)) % USB_PACKET_SIZE == 0:
                part = part[:-4]
            self.request(OP_WRITE, struct.pack("<I", address + offset) + part)
            offset += len(part)

    def read_memory(self, address, length):
        return self.request(OP_READ, struct.pack("<II", address, length))


def parse_nds(rom):
    """Returns (arm9, arm7) segments as dicts, after checking they are safe to boot."""
    if len(rom) < 0x200:
        raise DsError("File is too small to be an .nds ROM")

    segments = []
    for base in (0x20, 0x30):
        offset, entry, ram, size = struct.unpack_from("<4I", rom, base)
        if offset + size > len(rom):
            raise DsError(f"ROM segment at {offset:#x} runs past the end of the file")
        segments.append({"entry": entry, "ram": ram, "data": rom[offset:offset + size]})

    arm9, arm7 = segments
    if not ARM9_RAM_MIN <= arm9["ram"] or arm9["ram"] + len(arm9["data"]) > ARM9_RAM_END:
        raise DsError(f"ARM9 image at {arm9['ram']:#x} would overlap the display ring")
    if not ARM7_RAM_MIN <= arm7["ram"] or arm7["ram"] + len(arm7["data"]) > ARM7_RAM_END:
        raise DsError(f"ARM7 image at {arm7['ram']:#x} doesn't fit below shared memory")
    if len(arm9["data"]) + len(arm7["data"]) + 4 > STAGING_SIZE:
        raise DsError("ROM is too large for the upload area")
    return arm9, arm7


def upload_and_boot(link, rom):
    """Sends the ROM and asks the DS to reboot. Returns the CRC the new app will report."""
    arm9, arm7 = parse_nds(rom)
    arm9_source = STAGING_BASE
    arm7_source = (STAGING_BASE + len(arm9["data"]) + 3) & ~3
    crc = zlib.crc32(arm9["data"] + arm7["data"])

    link.write_memory(arm9_source, arm9["data"])
    link.write_memory(arm7_source, arm7["data"])
    link.request(OP_BOOT, struct.pack(
        "<9I", arm9_source, arm9["ram"], arm9["entry"], len(arm9["data"]),
        arm7_source, arm7["ram"], arm7["entry"], len(arm7["data"]), crc))
    return crc


def open_sd_drive(timeout=15.0):
    """Asks the DS to become a drive. Its dev port goes away until the drive is ejected."""
    with open_dev_port(timeout) as port:
        Link(port, on_log=lambda text: None).request(OP_SD_DRIVE)
    return dsupdate.wait_for_drive()


def install_on_sd(rom, filename):
    """Replaces filename on the SD card with rom. Returns where it went."""
    drive = open_sd_drive()
    try:
        target = dsupdate.locate(drive, filename)
        dsupdate.install(target, rom)
    finally:
        dsupdate.eject(drive)
    return target


def abgr1555_to_png(pixels, width=SCREEN_WIDTH, height=SCREEN_HEIGHT):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = bytearray()
    values = struct.unpack(f"<{width * height}H", pixels)
    for y in range(height):
        rows.append(0)
        for value in values[y * width:(y + 1) * width]:
            for channel in (value & 31, (value >> 5) & 31, (value >> 10) & 31):
                rows.append((channel << 3) | (channel >> 2))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
            + chunk(b"IEND", b""))


def command_push(args):
    rom = Path(args.file).read_bytes()
    started = time.monotonic()
    with open_dev_port() as port:
        crc = upload_and_boot(Link(port), rom)
    print(f"Uploaded {len(rom)} bytes in {time.monotonic() - started:.1f}s, rebooting...")

    time.sleep(1)  # Let the old device disappear before looking for the new one
    with open_dev_port(args.timeout) as port:
        status = Link(port).ping()
    if status["boot_crc"] != crc:
        raise DsError(f"DS came back running {status['boot_crc']:#010x}, expected {crc:#010x}")
    print(f"Running build {status['build']} ({crc:#010x}) after {time.monotonic() - started:.1f}s")


def command_install(args):
    path = Path(args.file)
    started = time.monotonic()
    target = install_on_sd(path.read_bytes(), path.name)
    print(f"Installed {target} in {time.monotonic() - started:.1f}s")


def command_drive(args):
    print(open_sd_drive(args.timeout))


def command_ping(args):
    with open_dev_port(args.timeout) as port:
        for key, value in Link(port).ping().items():
            print(f"{key}: {value:#x}" if key == "boot_crc" else f"{key}: {value}")


def command_log(args):
    while True:
        try:
            with open_dev_port(args.timeout) as port:
                port.timeout = None
                link = Link(port)
                while True:
                    op, _, data = link.read_frame()
                    if op == OP_LOG:
                        print(data.decode("utf-8", "replace"), end="", flush=True)
        except OSError:
            print("[disconnected, waiting for DS]", file=sys.stderr)


def command_shot(args):
    with open_dev_port(args.timeout) as port:
        pixels = Link(port).request(OP_SCREENSHOT)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(abgr1555_to_png(pixels))
    print(path)


def command_peek(args):
    with open_dev_port(args.timeout) as port:
        data = Link(port).read_memory(int(args.address, 0), int(args.length, 0))
    base = int(args.address, 0)
    for offset in range(0, len(data), 16):
        print(f"{base + offset:08x}  {data[offset:offset + 16].hex(' ')}")


def command_poke(args):
    with open_dev_port(args.timeout) as port:
        Link(port).write_memory(int(args.address, 0), bytes.fromhex(args.data))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=15.0, help="seconds to wait for the DS")
    commands = parser.add_subparsers(dest="command", required=True)

    push = commands.add_parser("push")
    push.add_argument("file", nargs="?", default=str(REPO_ROOT / "ds" / "usb-display.nds"))
    push.set_defaults(run=command_push)
    install = commands.add_parser("install")
    install.add_argument("file", nargs="?", default=str(REPO_ROOT / "ds" / "usb-display.nds"))
    install.set_defaults(run=command_install)
    commands.add_parser("drive").set_defaults(run=command_drive)
    commands.add_parser("ping").set_defaults(run=command_ping)
    commands.add_parser("log").set_defaults(run=command_log)
    shot = commands.add_parser("shot")
    shot.add_argument("output", nargs="?", default=str(REPO_ROOT / "build" / "screenshot.png"))
    shot.set_defaults(run=command_shot)
    peek = commands.add_parser("peek")
    peek.add_argument("address")
    peek.add_argument("length")
    peek.set_defaults(run=command_peek)
    poke = commands.add_parser("poke")
    poke.add_argument("address")
    poke.add_argument("data")
    poke.set_defaults(run=command_poke)

    args = parser.parse_args()
    try:
        args.run(args)
    except (DsError, dsupdate.UpdateError) as error:
        sys.exit(f"error: {error}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
