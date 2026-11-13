# DS Display: the DS app

Runs on a DS Lite or DSi with a DSpico, and shows what the PC app in [../app](../app) sends over
USB. The DSpico bridges USB to the DS, and the DS shows both screens as one 256×384 display.

```
┌─────────────┐     USB CDC      ┌─────────────┐    Cart Bus    ┌─────────────┐
│   PC        │◄──────────────►  │   DSpico    │◄─────────────► │   DS        │
│   app       │   Serial         │   (RP2040)  │   Card CMD +   │  (Homebrew) │
│             │                  │             │   IPC FIFO     │  ARM9+ARM7  │
└─────────────┘                  └─────────────┘                └─────────────┘
```

## Display Specifications

| Property | Value |
|----------|-------|
| Resolution | 256 × 384 pixels |
| Top Screen | 256 × 192 (Y: 0-191) |
| Bottom Screen | 256 × 192 (Y: 192-383) |
| Color Format | ABGR1555 (DS native) |
| Color Depth | 15-bit (32,768 colors) |
| Interface | USB CDC Serial |

## Protocol

The display stream on the first USB serial port is a series of length-prefixed
packets, defined in [common/DisplayProtocol.h](common/DisplayProtocol.h). The second
port is for dev tools, defined in [common/DebugProtocol.h](common/DebugProtocol.h).

USB data goes straight into a ring in main RAM. The ARM7 only moves data; the ARM9
parses packets and draws.

Pixels are ABGR1555, little-endian. Bit 15 must be set for a pixel to be visible.

## Performance

Measured figures are in [docs/DESIGN.md](../docs/DESIGN.md). Run `tools/ds_bench.py` to
measure, and `tools/test_ds_hw.py` to check drawing pixel for pixel.

## Sessions and what's on screen

A session starts with HELLO, which makes the DS black with no animations. Nothing else resets
them, so the PC app and the DS always agree on what's showing. Packets are what tell the DS the
host is there:

| State | When | On screen |
|---|---|---|
| Boot | No packet since power on | Startup diagnostics |
| Live | A packet in the last 5 seconds | The host's picture and animations |
| Asleep | Port open, but silent for 5 seconds | Sleep screen |
| Closed | The host closed the port | Black |

- **Asleep** covers a sleeping PC, a frozen app and a pulled cable. The DSpico can't detect an
  unplugged cable: it reports one as a bus suspend, the same as a sleeping PC. Bus suspend alone
  never ends a session.
- **Live** doesn't need the port's open flag (DTR). A bus reset when a PC wakes can clear the
  flag while the app's port stays open and keeps sending.
- The host sends a packet at least every second, a KEEPALIVE if nothing else.
- When packets return, the live picture comes back from the DS's own copy, and its animations
  start over.
- When the port closes, the ARM7 discards what's left of that session's data, so the next one
  starts on a packet boundary.

The PC app starts a new session whenever its link fails, and after any pause longer than
5 seconds, such as the PC sleeping.

## Animations

GIFs are uploaded once and play on the DS with no USB traffic. The DS keeps its own copy of the
live picture, and transparent animation pixels show it, so live values stay visible under a GIF.

The sleep screen is a black background with the sleep animation, from its own slot, at its own
brightness. The host's animations pause while it shows.

## Limitations

- Display only: no touchscreen input back to the PC
- 15-bit colour, the DS's own
- Needs a DSpico

## Credits

- [DSpico](https://github.com/LNH-team/dspico-firmware): open source DS flashcart
- [libtwl](https://github.com/blocksds/libtwl): DS homebrew library
- [TinyUSB](https://github.com/hathach/tinyusb): USB stack
