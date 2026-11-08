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

Measured figures are in [docs/PLAN.md](../docs/PLAN.md). Run `tools/ds_bench.py` to
measure, and `tools/test_ds_hw.py` to check drawing pixel for pixel.

## Reconnecting

The ARM7 watches DTR (`tud_cdc_connected`). When the host closes the port or the cable
is pulled, it discards the session's data, so the next session starts on a packet
boundary. The screens black out until the host reconnects, and brightness is restored.

The PC app finds the port again, repeats the HELLO handshake, and sends the whole screen and its
animations.

## Animations

GIFs are uploaded once and play on the DS with no USB traffic. The DS keeps its own copy of the
live picture, and transparent animation pixels show it, so live values stay visible under a GIF.

## Limitations

- Display only: no touchscreen input back to the PC
- 15-bit colour, the DS's own
- Needs a DSpico

## Credits

- [DSpico](https://github.com/LNH-team/dspico-firmware): open source DS flashcart
- [libtwl](https://github.com/blocksds/libtwl): DS homebrew library
- [TinyUSB](https://github.com/hathach/tinyusb): USB stack
