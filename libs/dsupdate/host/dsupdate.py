"""Host side of dsupdate: finds the DS's SD drive, installs files on it and ejects it.

Works on any folder, so the file handling can be tested without a DS. Finding, reading
past the cache and ejecting use the Windows API.
"""
import ctypes
import os
import string
import struct
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional

# Must match tud_msc_inquiry_cb in arm7/dsupdate.cpp.
DRIVE_VENDOR = "DSpico"
DRIVE_PRODUCT = "SD Transfer"

SEARCH_DEPTH = 4
SKIPPED_FOLDERS = {"System Volume Information", "$RECYCLE.BIN"}

GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ_WRITE = 3
OPEN_EXISTING = 3
FILE_FLAG_NO_BUFFERING = 0x20000000
INVALID_HANDLE = ctypes.c_void_p(-1).value
SECTOR_READ = 64 * 1024

IOCTL_STORAGE_QUERY_PROPERTY = 0x2D1400
IOCTL_STORAGE_MEDIA_REMOVAL = 0x2D4804
IOCTL_STORAGE_EJECT_MEDIA = 0x2D4808
FSCTL_LOCK_VOLUME = 0x90018
FSCTL_DISMOUNT_VOLUME = 0x90020


class UpdateError(Exception):
    pass


def _kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                     ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.FlushFileBuffers.argtypes = [ctypes.c_void_p]
    kernel32.ReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                  ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    kernel32.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                         ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                         ctypes.c_void_p]
    return kernel32


def _io_control(kernel32, handle, code, data=b"", out_size=0):
    output = ctypes.create_string_buffer(out_size)
    returned = ctypes.c_uint32()
    done = kernel32.DeviceIoControl(handle, code, data or None, len(data), output if out_size else None,
                                    out_size, ctypes.byref(returned), None)
    return output.raw[:returned.value] if done else None


def parse_device_descriptor(data):
    """Returns the (vendor, product) strings from a STORAGE_DEVICE_DESCRIPTOR."""
    def text(offset):
        if not offset or offset >= len(data):
            return ""
        return data[offset:data.index(b"\0", offset)].decode("ascii", "replace").strip()

    vendor_offset, product_offset = struct.unpack_from("<II", data, 12)
    return text(vendor_offset), text(product_offset)


def _is_update_drive(kernel32, letter):
    handle = kernel32.CreateFileW(f"\\\\.\\{letter}:", 0, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE:
        return False
    try:
        data = _io_control(kernel32, handle, IOCTL_STORAGE_QUERY_PROPERTY, bytes(12), 1024)
    finally:
        kernel32.CloseHandle(handle)
    return bool(data) and parse_device_descriptor(data) == (DRIVE_VENDOR, DRIVE_PRODUCT)


def find_drive() -> Optional[Path]:
    kernel32 = _kernel32()
    mask = kernel32.GetLogicalDrives()
    for index, letter in enumerate(string.ascii_uppercase):
        if mask >> index & 1 and _is_update_drive(kernel32, letter):
            return Path(f"{letter}:\\")
    return None


def wait_for_drive(timeout=30.0) -> Path:
    deadline = time.monotonic() + timeout
    while True:
        drive = find_drive()
        if drive and drive.exists():
            return drive
        if time.monotonic() >= deadline:
            raise UpdateError("The DS's SD drive didn't appear")
        time.sleep(0.25)


def locate(drive: Path, filename: str) -> Path:
    """Returns the one file called filename, looking a few folders deep."""
    found = []
    folders = deque([(Path(drive), 0)])
    while folders:
        folder, depth = folders.popleft()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if depth < SEARCH_DEPTH and entry.name not in SKIPPED_FOLDERS:
                    folders.append((Path(entry.path), depth + 1))
            elif entry.name.lower() == filename.lower():
                found.append(Path(entry.path))

    if not found:
        raise UpdateError(f"{filename} isn't on the SD card, so there's nothing to replace")
    if len(found) > 1:
        raise UpdateError(f"{filename} is on the SD card {len(found)} times: "
                          + ", ".join(str(path) for path in found))
    return found[0]


def read_from_disk(path: Path) -> bytes:
    """Reads a file back from the card itself, not from Windows' cache of what was written."""
    if sys.platform != "win32":
        return path.read_bytes()

    kernel32 = _kernel32()
    handle = kernel32.CreateFileW(str(path), GENERIC_READ, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING,
                                  FILE_FLAG_NO_BUFFERING, None)
    if handle == INVALID_HANDLE:
        raise UpdateError(f"Couldn't read {path} back")
    try:
        # Unbuffered reads need a sector-aligned buffer.
        raw = ctypes.create_string_buffer(SECTOR_READ + 4096)
        aligned = (ctypes.addressof(raw) + 4095) & ~4095
        data = bytearray()
        got = ctypes.c_uint32()
        while kernel32.ReadFile(handle, aligned, SECTOR_READ, ctypes.byref(got), None) and got.value:
            data += ctypes.string_at(aligned, got.value)
        return bytes(data)
    finally:
        kernel32.CloseHandle(handle)


def install(target: Path, data: bytes):
    """Replaces target, keeping the old file until the new one has been read back."""
    temporary = target.with_name(target.name + ".new")
    with open(temporary, "wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())

    if read_from_disk(temporary) != data:
        temporary.unlink()
        raise UpdateError("The file read back differently from what was written")
    os.replace(temporary, target)


def eject(drive: Path):
    """Flushes and ejects the drive, which tells the DS to go back to the app."""
    kernel32 = _kernel32()
    letter = str(drive)[0]
    handle = kernel32.CreateFileW(f"\\\\.\\{letter}:", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ_WRITE,
                                  None, OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE:
        raise UpdateError(f"Couldn't open drive {letter}: to eject it")
    try:
        kernel32.FlushFileBuffers(handle)
        # Explorer can hold the volume briefly. The dismount below works regardless.
        for _ in range(10):
            if _io_control(kernel32, handle, FSCTL_LOCK_VOLUME) is not None:
                break
            time.sleep(0.2)
        _io_control(kernel32, handle, FSCTL_DISMOUNT_VOLUME)
        _io_control(kernel32, handle, IOCTL_STORAGE_MEDIA_REMOVAL, b"\0")
        if _io_control(kernel32, handle, IOCTL_STORAGE_EJECT_MEDIA) is None:
            raise UpdateError(f"Windows wouldn't eject drive {letter}:")
    finally:
        kernel32.CloseHandle(handle)
