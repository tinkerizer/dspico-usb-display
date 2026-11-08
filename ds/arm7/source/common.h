#pragma once
#include <nds.h>
#include <libtwl/rtos/rtosMutex.h>

extern rtos_mutex_t gCardMutex;
extern rtos_mutex_t gI2cMutex;

// Records ARM7 startup progress for the ARM9 to draw. Plain address so the
// platform layer can use it without the display headers.
#define BOOT_STAGE(stage)   (*(vu8*)0x023F0038 = (stage))

// Counts passes of the USB event thread, for the on-screen heartbeat.
#define USB_EVENT_TICK()    (*(vu8*)0x023F003B = *(vu8*)0x023F003B + 1)

// Set just before a reboot that leaves the DSpico's USB controller initialized.
// The next dcd_init then reconnects instead of sending the INIT command.
#define USB_WARM_BOOT_FLAG  (*(vu32*)0x0237FFF4)
#define USB_WARM_BOOT_MAGIC 0x55534221

/// @brief Makes the USB event thread check for events without a card IRQ.
void dspico_pollUsbEvents();
