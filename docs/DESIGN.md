# Design notes

For working on the code. What the project does and what's planned is in [PLAN.md](PLAN.md).

## Decisions

- **USB only.** The theme needs about 74 KB/s (estimated) of a ~1 MB/s link. Other links
  need a USB bridge anyway and don't change the ARM7 bottleneck.
- **The device stays on Windows.** The PC app runs there (COM3/COM4) and owns the
  port. WSL drives the DS through Windows interop, not by taking the USB device.
- **Two USB serial ports.** Port 0 is display data, port 1 is dev control and logs.
  Pushing code never fights the PC app for the COM port.
- **GIFs are uploaded once and played on the DS.** Streaming a full screen costs 96 KB per
  frame, about 10 fps at best, and would starve the stats. Stored playback uses no USB
  after upload.
- **The ARM9 does the work.** The ARM7 only moves USB data into memory; the ARM9
  parses, decompresses and draws.
- **Its own protocol.** Only this project's PC app talks to the DS, so the protocol fits it.

## How the PC app draws

The app renders the whole 256x384 picture each second and sends only the parts that changed, so
the web preview matches the DS. New frames replace old ones, so a slow link skips ahead instead
of building a backlog. A GIF is uploaded once and the ARM9 plays it, so its frames use no USB.

## Measurements

Measured with random pixels, before and after USB data went straight into the ring buffer:

| Update | Baseline (build 5) | Ring buffer (build 6) |
|---|---|---|
| Full frame | 582 KB/s, 330 ms | 720 KB/s, 266 ms |
| One screen | 580 KB/s, 165 ms | 719 KB/s, 133 ms |
| Graph 110x28 | 578 KB/s, 10.4 ms | 692 KB/s, 8.7 ms |
| Text 56x12 | 578 KB/s, 2.3 ms | 664 KB/s, 2.0 ms |
| Tiny 8x8 | 275 KB/s, 0.48 ms | 324 KB/s, 0.43 ms |

The dev port reached 765 KB/s with no pixel handling, which is about the ceiling of the
current USB path. Going faster needs less data or DSpico firmware changes.
The stats theme measures about 55 KB/s.

Sending only what changed, and RLE where it's smaller, brought the default dashboard down to
about 0.4 KB/s, with or without an animation playing.

## Restarting the DS app over USB

The restart uses a small stub in this repo, not Pico Loader: the ARM7 runs from its own
work RAM and the ARM9 stub from ITCM, so each can overwrite the app in main RAM. Pico
Loader's multiboot needed its binaries, a DLDI driver and the ROM already in place.

USB stays initialized across a restart. The DSpico `DEINIT` command followed by `INIT`
left USB dead on hardware, so the stub only disconnects and the new app reconnects.

A crash that kills the ARM7 kills USB too, so that still needs a power cycle.

## SD card updates

`tools/ds push` only lives in RAM. `tools/ds install` replaces `apps/usb-display.nds` on the
SD card as well, and the app does the same once for each new bundled build. Both use
[`libs/dsupdate`](../libs/dsupdate/README.md): the DS swaps its USB device for a drive, then swaps
back when the drive is ejected or left idle for a minute. It costs the display nothing the
rest of the time. `tools/ds drive` opens the drive for copying files by hand.

## DSpico core

Core repos live in `dspico/` and are forked only when first changed (see README).

- [ ] Update to current Pico Launcher and Pico Loader. Touch input is already upstream
      (launcher v1.3.0+), so test that before writing any touch code.
- [ ] Update firmware to upstream, and reflash.
- [ ] Dev features to consider: reboot the RP2040 to BOOTSEL by command instead of ejecting
      the SD, and autoboot straight into usb-display after power-on.

Firmware changes need a reflash via BOOTSEL, so test those separately from DS app changes.

## Open problems

- Large animations can tear. The bottom screen can't double-buffer: VRAM C is 128 KB and a
  frame is 96 KB.
- The animation store is 512 KB. 1.75 MB is possible by sharing the push staging area.
- The preview's pixels aren't exact at fractional Windows scaling.

## Optional: USB in WSL

For Linux-only USB tools. While attached, Windows and the PC app lose the device.

```powershell
winget install --exact dorssel.usbipd-win
usbipd bind --hardware-id 1209:dd01                     # once, as admin; persists
usbipd attach --wsl --hardware-id 1209:dd01 --auto-attach   # reattaches after re-enumeration
```

Then in WSL: `sudo modprobe cdc_acm`, and the device is `/dev/ttyACM0`. Attach has to be
running for auto-attach to work, so start it from a logon task if it should be permanent.
