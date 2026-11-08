#pragma once
#include <nds/ndstypes.h>

// Live updates for DSpico homebrew: lends the SD card to the host as a USB drive,
// then hands USB back to the app. See ../README.md.

#ifndef DSUPDATE_USB_VID
#define DSUPDATE_USB_VID    0x1209
#endif
#ifndef DSUPDATE_USB_PID
#define DSUPDATE_USB_PID    0xDD02  // Must differ from the app's: Windows caches descriptors by ID
#endif

// The drive goes away after this many waitTick calls with no reads or writes.
#ifndef DSUPDATE_IDLE_TICKS
#define DSUPDATE_IDLE_TICKS (60 * 60)
#endif

// Starts the SD driver. False if the build has no driver or there is no card.
bool dsupdate_prepare();

// Swaps the app's USB device for the drive and returns once the host has ejected
// it or left it idle, with the app's device back. Call after dsupdate_prepare, on
// a thread other than the one running tud_task. waitTick should wait for about a
// VBlank. Anything else using the card must hold gCardMutex.
void dsupdate_run(void (*waitTick)());

// While this is true, the app's descriptor callbacks return the ones below.
bool dsupdate_active();
const u8* dsupdate_deviceDescriptor();
const u8* dsupdate_configurationDescriptor();
const u16* dsupdate_stringDescriptor(u8 index);
