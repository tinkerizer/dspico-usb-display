"""Host-side tests for dsctl.py against a fake device. Hardware is not needed."""
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
import dsctl
import dsupdate


class FakeDevice:
    """Implements the device side of the protocol, mirroring ds/arm7/source/debug.cpp."""

    def __init__(self):
        self.memory = {}
        self.reply = bytearray()
        self.boot = None
        self.pending_log = b""

    def _send(self, op, status=0, payload=b""):
        if self.pending_log:
            self.reply += dsctl.FRAME.pack(dsctl.FRAME_MAGIC, dsctl.OP_LOG, 0, len(self.pending_log))
            self.reply += self.pending_log
            self.pending_log = b""
        self.reply += dsctl.FRAME.pack(dsctl.FRAME_MAGIC, op, status, len(payload)) + payload

    def write(self, data):
        _, op, _, length = dsctl.FRAME.unpack_from(data)
        payload = data[dsctl.FRAME.size:]
        assert len(payload) == length
        if op == dsctl.OP_PING:
            self._send(op, payload=struct.pack("<7I", dsctl.PROTOCOL_VERSION, 0xABCD, 1, 2, 3, 3, 42))
        elif op == dsctl.OP_WRITE:
            address = struct.unpack_from("<I", payload)[0]
            for index, value in enumerate(payload[4:]):
                self.memory[address + index] = value
            self._send(op)
        elif op == dsctl.OP_READ:
            address, size = struct.unpack("<II", payload)
            self._send(op, payload=bytes(self.memory.get(address + i, 0) for i in range(size)))
        elif op == dsctl.OP_BOOT:
            info = struct.unpack("<9I", payload)
            image = b"".join(
                bytes(self.memory[source + i] for i in range(size))
                for source, size in ((info[0], info[3]), (info[4], info[7])))
            if zlib.crc32(image) != info[8]:
                self._send(op, status=2)
            else:
                self.boot = info
                self._send(op)
        else:
            self._send(op, status=1)

    def read(self, size):
        data = bytes(self.reply[:size])
        del self.reply[:size]
        return data


def make_rom(arm9=b"\x11" * 1001, arm7=b"\x22" * 503, arm9_ram=0x02000000, arm7_ram=0x02380000):
    rom = bytearray(0x4000)
    struct.pack_into("<4I", rom, 0x20, 0x4000, arm9_ram + 0x800, arm9_ram, len(arm9))
    struct.pack_into("<4I", rom, 0x30, 0x4000 + len(arm9), arm7_ram, arm7_ram, len(arm7))
    return bytes(rom) + arm9 + arm7


class DsctlTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeDevice()
        self.logs = []
        self.link = dsctl.Link(self.device, on_log=self.logs.append)

    def test_ping(self):
        status = self.link.ping()
        self.assertEqual(status["boot_crc"], 0xABCD)
        self.assertEqual(status["build"], 42)

    def test_log_frames_between_replies_are_delivered(self):
        self.device.pending_log = b"hello\n"
        self.link.ping()
        self.assertEqual(self.logs, ["hello\n"])

    def test_memory_round_trip_across_chunks(self):
        data = bytes(range(256)) * 300
        self.link.write_memory(0x02200000, data)
        self.assertEqual(self.link.read_memory(0x02200000, len(data)), data)

    def test_upload_boots_with_matching_crc(self):
        crc = dsctl.upload_and_boot(self.link, make_rom())
        info = self.device.boot
        self.assertEqual(info[8], crc)
        self.assertEqual(info[1:4], (0x02000000, 0x02000800, 1001))
        self.assertEqual(info[4] % 4, 0)
        self.assertEqual(info[5:8], (0x02380000, 0x02380000, 503))

    def test_device_error_is_reported(self):
        with self.assertRaisesRegex(dsctl.DsError, "bad request"):
            self.link.request(0x55)

    def test_short_reply_times_out(self):
        with self.assertRaisesRegex(dsctl.DsError, "Timed out"):
            self.link.read_frame()

    def test_rejects_images_that_overlap_reserved_memory(self):
        with self.assertRaisesRegex(dsctl.DsError, "ARM9"):
            dsctl.parse_nds(make_rom(arm9_ram=0x020FFF00))
        with self.assertRaisesRegex(dsctl.DsError, "ARM7"):
            dsctl.parse_nds(make_rom(arm7_ram=0x023EFF00, arm7=b"\0" * 0x1000))

    def test_real_build_parses(self):
        rom = Path(__file__).parent.parent / "ds" / "usb-display.nds"
        if rom.exists():
            arm9, arm7 = dsctl.parse_nds(rom.read_bytes())
            self.assertEqual(arm9["ram"], 0x02000000)
            self.assertEqual(arm7["ram"], 0x02380000)

    def test_dev_port_selection(self):
        def port(device, location, vid=dsctl.USB_VID):
            return SimpleNamespace(device=device, location=location, vid=vid, pid=dsctl.USB_PID)

        self.assertEqual(dsctl.find_dev_port([port("COM3", "1-4:x.0"), port("COM4", "1-4:x.2")]), "COM4")
        self.assertEqual(dsctl.find_dev_port([port("/dev/ttyACM0", "1-1:1.0"), port("/dev/ttyACM1", "1-1:1.2")]),
                         "/dev/ttyACM1")
        self.assertIsNone(dsctl.find_dev_port([port("COM3", "1-4:x.0")]))
        self.assertIsNone(dsctl.find_dev_port([port("COM5", "1-4:x.2", vid=0x2E8A)]))

    def test_png_has_expected_size_and_colour(self):
        png = dsctl.abgr1555_to_png(struct.pack("<H", 0x801F) * 4, width=2, height=2)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", png[16:24]), (2, 2))
        idat = png.index(b"IDAT") + 4
        self.assertEqual(zlib.decompressobj().decompress(png[idat:])[1:4], b"\xff\x00\x00")


class WriteFrameTests(unittest.TestCase):
    def test_no_write_fills_its_last_usb_packet(self):
        frames = []
        link = dsctl.Link(None)
        link.request = lambda op, payload: frames.append(payload)
        data = bytes(range(256)) * 200
        for length in (52, 16500, 32768 + 16500, len(data)):
            frames.clear()
            link.write_memory(0x02200000, data[:length])
            self.assertEqual(b"".join(frame[4:] for frame in frames), data[:length])
            self.assertTrue(all((dsctl.FRAME.size + len(frame)) % 64 for frame in frames))


class SdFileTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.drive = Path(folder.name)

    def add(self, name):
        path = self.drive / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old")
        return path

    def test_finds_a_file_in_a_folder(self):
        path = self.add("apps/usb-display.nds")
        self.add("apps/other.nds")
        self.assertEqual(dsupdate.locate(self.drive, "USB-display.nds"), path)

    def test_refuses_to_guess_between_copies(self):
        self.add("apps/usb-display.nds")
        self.add("old/usb-display.nds")
        with self.assertRaisesRegex(dsupdate.UpdateError, "2 times"):
            dsupdate.locate(self.drive, "usb-display.nds")

    def test_never_adds_a_file_that_is_not_there(self):
        with self.assertRaisesRegex(dsupdate.UpdateError, "isn't on the SD card"):
            dsupdate.locate(self.drive, "usb-display.nds")

    def test_install_replaces_the_file(self):
        path = self.add("apps/usb-display.nds")
        dsupdate.install(path, b"new")
        self.assertEqual(path.read_bytes(), b"new")
        self.assertEqual([entry.name for entry in path.parent.iterdir()], [path.name])

    def test_keeps_the_old_file_if_the_copy_reads_back_wrong(self):
        path = self.add("apps/usb-display.nds")
        original = dsupdate.read_from_disk
        dsupdate.read_from_disk = lambda _: b"corrupt"
        self.addCleanup(setattr, dsupdate, "read_from_disk", original)
        with self.assertRaises(dsupdate.UpdateError):
            dsupdate.install(path, b"new")
        self.assertEqual(path.read_bytes(), b"old")
        self.assertEqual([entry.name for entry in path.parent.iterdir()], [path.name])

    def test_reads_the_drive_name(self):
        data = bytearray(64)
        struct.pack_into("<II", data, 12, 40, 48)
        data[40:47] = b"DSpico\0"
        data[48:60] = b"SD Transfer\0"
        self.assertEqual(dsupdate.parse_device_descriptor(bytes(data)), ("DSpico", "SD Transfer"))


if __name__ == "__main__":
    unittest.main()
