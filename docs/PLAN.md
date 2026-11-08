# usb-display roadmap

Goal: a fast, smooth DS dashboard that can also show GIFs, with a dev loop measured
in seconds. USB stays as the only data link.

Throughput figures here are calculated, not measured. Phase 0 replaces them with
real numbers, and later targets should be revisited once it has run.

## Design decisions

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

## Phase 0: baseline

- [x] Put `usb-display` under version control.
- [ ] Confirm the odd-width blit fix on hardware (CPU/GPU graphs).
- [x] Add `tools/ds_bench.py`.

Measured with random pixels, before and after Phase 2:

| Update | Baseline (build 5) | Ring buffer (build 6) |
|---|---|---|
| Full frame | 582 KB/s, 330 ms | 720 KB/s, 266 ms |
| One screen | 580 KB/s, 165 ms | 719 KB/s, 133 ms |
| Graph 110x28 | 578 KB/s, 10.4 ms | 692 KB/s, 8.7 ms |
| Text 56x12 | 578 KB/s, 2.3 ms | 664 KB/s, 2.0 ms |
| Tiny 8x8 | 275 KB/s, 0.48 ms | 324 KB/s, 0.43 ms |

The dev port reached 765 KB/s with no pixel handling, which is about the ceiling of the
current USB path. Going faster needs less data (Phase 3) or firmware changes (Phase 5).
The stats theme measures about 55 KB/s.

## Phase 1: dev loop

Working on hardware. Everything runs over the existing USB cable.

- [x] Second CDC interface for control and logs (`ds/common/DebugProtocol.h`).
- [x] `LcdCommRevDS` auto-detect selects interface 0 only.
- [x] `tools/dsctl.py` and `make -C ds push`: upload, CRC check, reboot, confirm new build.
- [x] Debug commands: ping, log stream, screenshot, memory peek and poke.
- [x] ARM9 crash reports, and pushes still work after an ARM9 crash or hang.
- [x] First load by SD, then verify on hardware (below).
- [x] Build number on the DS and in `ping`, bumped when DS sources change.
- [ ] Add `make test`: push, screenshot, compare against a reference image.

The restart uses a small stub in this repo, not Pico Loader: the ARM7 runs from its own
work RAM and the ARM9 stub from ITCM, so each can overwrite the app in main RAM. Pico
Loader's multiboot needed its binaries, a DLDI driver and the ROM already in place.

USB stays initialized across a restart. The DSpico `DEINIT` command followed by `INIT`
left USB dead on hardware, so the stub only disconnects and the new app reconnects.

Hardware results:

- [x] Two COM ports appear (COM3 display, COM4 dev).
- [x] `ping`, `shot`, `peek` and log output work.
- [x] Push takes about 1.5 seconds. Five in a row succeeded.
- [x] After a deliberate ARM9 crash: registers are reported and a push recovers it.
- [x] After a deliberate ARM9 main-loop hang: a push recovers it.
- [x] The display app runs on COM3 alongside the dev port, and reconnects after a push. An early USB stall after a push stopped once events were polled each frame.
- [x] Odd-width blit fix confirmed on the CPU graph (GPU graph has no data to draw yet).

Target met: edit to running code takes about 3 seconds without touching the DS.
Limit: a crash that kills the ARM7 kills USB too, so it still needs a manual power cycle.

## Phase 2: protocol v2 and ARM7 fast path

Working on hardware. `tools/test_ds_hw.py` compares drawn rects to a screenshot, pixel for pixel.

- [x] Length-prefixed packets with word alignment; HELLO replies with the protocol version.
- [x] Commands: `RECT_RAW`, `CLEAR`, `BRIGHTNESS`, `POWER`, with IDs reserved for
      `COPY_RECT`, `FRAME_END` and the Phase 4 asset commands.
- [x] USB data read straight into a 512 KB main-RAM ring; ARM7 no longer touches pixels.
- [x] Parsing and drawing moved to the ARM9.
- [x] Update `ds/README.md` for the new protocol.

## Phase 3: send less from the host

Working on hardware. Steady ClassicDS traffic fell from about 55 KB/s to about 0.4 KB/s
(measured with the network and GPU panels idle, so busier readings will cost more).

- [x] Keep a copy of the screen on the host; skip unchanged widgets and shrink each update
      to its changed area.
- [x] One USB write per update.
- [x] Use `RECT_RLE` when smaller. The ClassicDS background is 192 KB raw, 19 KB RLE.
- [ ] `COPY_RECT` for scrolling graphs: dropped for now, since traffic is already tiny.
      Revisit only if a theme needs it.

## Phase 4: GIFs and animation

Working on hardware. A GIF uploads once and the ARM9 plays it, so frames use no USB:
traffic stayed at about 0.4 KB/s with an animation running.

- [x] `ANIM_BEGIN`, `ANIM_FRAME`, `ANIM_PLAY`, `ANIM_STOP`, `ANIM_RESET` packets, 8 slots.
- [x] Host encoder: first frame plus changed-area frames, with transparent pixels marked by
      bit 15 clear. Per-frame delays are kept.
- [x] Transparency on the DS: the ARM9 keeps a copy of the live picture and which animation
      covers each pixel, so live values show through a GIF's transparent parts.
- [x] ARM9 player, timed from VBlank, running alongside stat updates.
- [x] 512 KB store. Oversized assets are rejected on the host.
- [ ] Confirm animations come back after a push or reconnect.
- [ ] Bigger store if needed: 1.75 MB is possible by sharing the push staging area.
- [ ] Tearing on larger animations. The bottom screen can't double-buffer: VRAM C is
      128 KB and a frame is 96 KB.

## Phase 5: only if needed

RP2040 firmware changes (bigger card transfers, buffering on the RP2040) are only worth it
for live video. Card bus ceiling is about 34 fps for uncompressed full frames.

## Phase 6: PC app

First version working on hardware, replacing the earlier stats app. Run `app/run.py` with Windows
Python, then open http://127.0.0.1:8765. The first version needs no new packages.

The app renders the whole 256x384 screen each tick and sends only changed rects, so the
web preview matches the DS and every widget gets efficient updates for free. New frames
replace old ones, so a slow link skips ahead instead of building a backlog.

- [x] One thread owns the display port, with reconnect and animation re-upload.
- [x] Sensors, rendering, device and web server as separate modules, with tests.
- [x] Web UI in the DS style: real menu art, pixel font, menu sounds, popouts and a drawer.
      Motion and Floating UI are stored in `dsdash/web/vendor`, so it works offline.
- [x] Live preview, status, brightness, image and GIF upload.
- [x] Layouts are data (`dsdash/layout.py`): elements with a schema, validated on the server.
- [x] Layout editor: drag, resize, nudge, undo, add, delete, reorder, hide, lock, and
      a properties panel built from the schema. Changes reach the DS as you make them.
- [x] Cropping, aspect lock and pixel scale lock for images and GIFs.
- [x] Layout JSON panel with highlighting, live checks and links to the selection.
- [x] `DS Display Setup.exe` from `app/build_windows.py`: per-user install, Start Menu,
      autostart, tray icon and uninstall. It bundles the art, so keep it to yourself.
- [ ] Settings saved between runs.
- [x] GPU load, GPU memory and temperature: NVML on NVIDIA, Windows counters otherwise.
      NVML hasn't been run on real hardware yet.
- [x] Multiple saved layouts: each theme is a folder with its own layout, colours, art and
      uploads. See [THEMES.md](THEMES.md).
- [x] Templates and element types, so others can add elements. See [THEMES.md](THEMES.md).
- [x] Small preview of the whole DS, and a screens-only editor at 2x or more, with snapping.
- [x] Versioned releases: `VERSION`, `CHANGELOG.md` and `tools/release`.
- [ ] DS status and logs in the web UI.

## Phase 7: DS home screen dashboard

Working, as the default layout. It follows the real menu's structure: clock and calendar on
top, then a game card, two panels, a slim slot and the footer strip. Buttons are the real
`grf/box.bmp` art, stretched by its edges. The art is in each theme's folder, in
`app/assets/themes/`.

- [ ] Use more of the menu art: icons, shoulder buttons, battery and volume indicators.

## Phase 8: DS shell around the web preview

Working in the web UI. The preview sits inside a front view of an open DS Lite, with a real
gap for the hinge.

- [x] Shell drawn as `dsdash/web/shell.svg`, not taken from a photo, so it is committed and
      bundled with the rest of the web UI. Tracing a JPEG gave wobbly shapes, so it uses plain
      shapes at sizes measured from a reference picture. No logos.
- [x] Measured in DS pixels: screens are exactly 256x192, 101 pixels apart.
- [x] Shell colour picker: swatches or any custom colour, kept in the browser. It sets
      `--ds-color`, and switches `--ds-label` to dark on pale shells.
- [x] Hinge gap in the preview only. Layouts stay 256x384. `viewTop`, `viewBottom` and
      `fromView` in `app.js` convert rows, and a drag that stops in the hinge lands on the seam.
- [x] Preview snaps to whole device pixels per DS pixel, sized so the whole shell fits, with
      the tools in a row below it. **Fill** sizes it to the window instead.
- [ ] Pixels aren't exact at fractional Windows scaling (125%, some sizes at 150%).
- [ ] Web UI sometimes stalls or won't load. Windows TCP timers looked stopped: `TIME_WAIT`
      never expired, and a new connection that landed on an old one hung. The server now
      closes with a reset and leaves none. Old ones on 8765 should need a reboot, not yet tried.
- [ ] DS link drops often with `WriteFile failed`. Not yet known if that's hardware.
- [x] Editor checked in Chrome at four window sizes: drag, resize, undo, redo, nudge, add,
      delete and animations across the seam. The script isn't in the repo yet.

## DSpico core changes

Core repos live in `dspico/` and are forked only when first changed (see README).

- [ ] Update to current Pico Launcher and Pico Loader. Touch input is already upstream
      (launcher v1.3.0+), so test that before writing any touch code.
- [ ] Update firmware to upstream, and reflash.
- [ ] Dev features to consider: reboot the RP2040 to BOOTSEL by command instead of ejecting
      the SD, and autoboot straight into usb-display after power-on.

Firmware changes need a reflash via BOOTSEL, so test those separately from DS app changes.

## SD card updates

`tools/ds push` only lives in RAM. `tools/ds install` replaces `apps/usb-display.nds` on the
SD card as well, and the app does the same once for each new bundled build. Both use
[`libs/dsupdate`](../libs/dsupdate/README.md): the DS swaps its USB device for a drive, then swaps
back when the drive is ejected or left idle for a minute. It costs the display nothing the
rest of the time. `tools/ds drive` opens the drive for copying files by hand.

## Optional: USB in WSL

For Linux-only USB tools. While attached, Windows and the PC app lose the device.

```powershell
winget install --exact dorssel.usbipd-win
usbipd bind --hardware-id 1209:dd01                     # once, as admin; persists
usbipd attach --wsl --hardware-id 1209:dd01 --auto-attach   # reattaches after re-enumeration
```

Then in WSL: `sudo modprobe cdc_acm`, and the device is `/dev/ttyACM0`. Attach has to be
running for auto-attach to work, so start it from a logon task if it should be permanent.
