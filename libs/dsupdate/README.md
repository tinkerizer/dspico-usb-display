# dsupdate

Lets a running DSpico homebrew lend its SD card to the host as a USB drive, so a new build
can be copied on without taking the card out or leaving the app. When the host ejects the
drive, or leaves it idle for a minute, the app's own USB device comes back. No reboot, and
nothing runs until the app asks for it.

The ARM7 side is the whole of the DS part. It needs the DSpico USB driver in `platform/`.

## Adding it to an app

1. **ARM7 Makefile:** add `libs/dsupdate/arm7` and TinyUSB's `class/msc` to `SOURCES`, and
   `libs/dsupdate/arm7` to `INCLUDES`.
2. **`tusb_config.h`:** set `CFG_TUD_MSC 1` and `CFG_TUD_MSC_EP_BUFSIZE 8192`.
3. **ARM7 linker script:** it must leave `0x037F8000`-`0x037FBFFF` free for the SD driver, as
   `dldi_ds_arm7.ld` does. Add these two output sections. The first goes after `.crt0`, and
   the second moves the 8 KB USB buffer out of IWRAM, so goes before `.bss`:

   ```
   .ewram : { KEEP(*(.ewram)) } >ewram :crt0
   .ewram_bss (NOLOAD) : ALIGN(4) { *(.bss._mscd_epbuf) } >ewram :NONE
   ```

   See `ds/arm7/dldi_ds_arm7.ld` for how `.bss` then keeps its place in IWRAM.
4. **Descriptor callbacks:** start each with a check, for example:

   ```cpp
   const u8* tud_descriptor_device_cb(void)
   {
       if (dsupdate_active())
           return dsupdate_deviceDescriptor();
       ...
   ```

   Do the same for the configuration and string callbacks.
5. **Trigger it** however suits the app, from any thread except the one running `tud_task`:

   ```cpp
   if (dsupdate_prepare())
       dsupdate_run(waitForVBlank);
   ```

6. **Patch the ROM** after `ndstool`, as the driver has to be there for RAM-pushed builds too:

   ```
   dlditool libs/dsupdate/DSpico.dldi app.nds
   ```

## Host side

`host/dsupdate.py` has no dependencies:

```python
drive = dsupdate.wait_for_drive()
try:
    dsupdate.install(dsupdate.locate(drive, "app.nds"), rom)
finally:
    dsupdate.eject(drive)
```

`install` writes a `.new` file beside the target, reads it back past Windows' cache, then
swaps it in, so a bad copy leaves the old file alone. Finding and ejecting the drive are
Windows only for now.

## Good to know

- SD and USB share the card bus, so anything else on the card must hold `gCardMutex`.
- While the drive is open the app has no USB. If it reads the app's serial ports, expect them
  to go away and come back.
- `DSUPDATE_USB_PID` must differ from the app's, because Windows caches descriptors by ID.
- `DSpico.dldi` is from [dspico-dldi](https://github.com/LNH-team/dspico-dldi). See
  `DSpico.dldi.LICENSE.txt`. `dldi_stub.s` and the card size code come from the
  dspico-usb-examples mass storage example.
