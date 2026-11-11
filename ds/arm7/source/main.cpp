#include "common.h"
#include "stdio.h"
#include "tusb_config.h"
#include "usb_descriptors.h"
#include <libtwl/rtos/rtosIrq.h>
#include <libtwl/rtos/rtosThread.h>
#include <libtwl/rtos/rtosEvent.h>
#include <libtwl/ipc/ipcSync.h>
#include <libtwl/ipc/ipcFifoSystem.h>
#include <libtwl/sys/sysPower.h>
#include <libtwl/sio/sioRtc.h>
#include <libtwl/sio/sio.h>
#include <libtwl/gfx/gfxStatus.h>
#include <libtwl/mem/memSwap.h>
#include <libtwl/mem/memExtern.h>
#include <libtwl/i2c/i2cMcu.h>
#include <libtwl/spi/spiPmic.h>
#include "tusb.h"

#include "DisplayProtocol.h"
#include "IpcChannels.h"
#include "debug.h"

rtos_mutex_t gCardMutex;
rtos_mutex_t gI2cMutex;

//--------------------------------------------------------------------
// State
//--------------------------------------------------------------------

enum class ExitMode { Reset, PowerOff };
static ExitMode     sExitMode;
static bool         sExitRequested = false;
static volatile u8  sMcuIrqFlag = false;

// Main-loop wake event: signalled by VBlank (housekeeping tick) and by the
// CDC RX callback (new USB data). Waking on RX instead of only VBlank
// removes up to 16 ms of latency per buffer drain, which matters a lot for
// sustained pixel throughput.
static rtos_event_t sMainWakeEvent;

//--------------------------------------------------------------------
// USB thread — pure tud_task() loop, exactly like usb-video.
//--------------------------------------------------------------------

static rtos_thread_t sUsbThread;
static u32           sUsbThreadStack[512];

static void usbThreadMain(void*)
{
    while (true)
        tud_task();
}

//--------------------------------------------------------------------
// IRQ handlers
//--------------------------------------------------------------------

static void vblankIrq(u32)
{
    SHARED_DISPLAY->vblankTick = SHARED_DISPLAY->vblankTick + 1;
    rtos_signalEvent(&sMainWakeEvent);
    debug_wake();
    dspico_pollUsbEvents();
}

static void mcuIrq(u32)
{
    sMcuIrqFlag = true;
}

// Called by TinyUSB (USB thread context) whenever new CDC data arrives.
// Wakes the main loop immediately instead of waiting for the next VBlank.
void tud_cdc_rx_cb(u8 itf)
{
    if (itf == DEBUG_CDC_ITF)
        debug_wake();
    else
        rtos_signalEvent(&sMainWakeEvent);
}

void tud_cdc_tx_complete_cb(u8 itf)
{
    if (itf == DEBUG_CDC_ITF)
        debug_wake();
}

//--------------------------------------------------------------------
// Init
//--------------------------------------------------------------------

static void initializeSharedMemory()
{
    volatile SharedDisplayMemory* s = SHARED_DISPLAY;
    s->arm7Ready      = 0;
    s->arm9Ready      = 0;
    s->usbConnected   = 0;
    s->ringHead       = 0;
    s->ringTail       = 0;
    s->ringGeneration = 0;
    s->logHead        = 0;
    s->logTail        = 0;
    s->captureCount   = 0;
    s->helloRequests  = 0;
    s->packetCount    = 0;
}

static void initializeArm7()
{
    rtos_initIrq();
    rtos_startMainThread();
    ipc_initFifoSystem();

    dmaFillWords(0, (void*)0x04000400, 0x100);
    readUserSettings();
    pmic_setPowerLedBlink(PMIC_CONTROL_POWER_LED_BLINK_NONE);
    sio_setGpioSiIrq(false);
    sio_setGpioMode(RCNT0_L_MODE_GPIO);
    rtc_init();

    // VBlank event (for ARM7/ARM9 sync wait)
    rtos_createEvent(&sMainWakeEvent);
    rtos_setIrqFunc(RTOS_IRQ_VBLANK, vblankIrq);
    rtos_enableIrqMask(RTOS_IRQ_VBLANK);
    gfx_setVBlankIrqEnabled(true);

    if (isDSiMode())
    {
        rtos_setIrq2Func(RTOS_IRQ2_MCU, mcuIrq);
        rtos_enableIrq2Mask(RTOS_IRQ2_MCU);
    }

    initializeSharedMemory();

    // Signal ARM9, then wait for it.
    BOOT_STAGE(1);
    SHARED_DISPLAY->arm7Ready = 1;
    ipc_setArm7SyncBits(7);
    while (ipc_getArm9SyncBits() != 6)
        rtos_waitEvent(&sMainWakeEvent, true, true);

    BOOT_STAGE(2);

    // Start TinyUSB.
    tusb_rhport_init_t dev_init = { .role = TUSB_ROLE_DEVICE, .speed = TUSB_SPEED_AUTO };
    tusb_init(0, &dev_init);
    BOOT_STAGE(5);

    // USB thread: pure tud_task() loop, exactly like usb-video.
    rtos_createThread(&sUsbThread, 8, usbThreadMain, nullptr, sUsbThreadStack, sizeof(sUsbThreadStack));
    rtos_wakeupThread(&sUsbThread);
    BOOT_STAGE(6);

    debug_init();
    BOOT_STAGE(7);
}

//--------------------------------------------------------------------
// Main loop
//--------------------------------------------------------------------

// Moves available USB data into the ring. Returns false if there was nothing to do.
static bool fillRing()
{
    const u32 head = SHARED_DISPLAY->ringHead;
    const u32 tail = SHARED_DISPLAY->ringTail;
    const u32 offset = head & DISPLAY_RING_MASK;

    u32 length = DISPLAY_RING_SIZE - (head - tail);
    if (length > DISPLAY_RING_SIZE - offset)
        length = DISPLAY_RING_SIZE - offset;
    if (length == 0)
        return false;   // Full: USB flow control holds the host back

    u32 got = tud_cdc_read((void*)(DISPLAY_RING_BASE + offset), length);
    if (got == 0)
        return false;

    SHARED_DISPLAY->ringHead = head + got;

    // Only needed if the ARM9 had caught up. Otherwise it is still draining and
    // will see the new head, which also keeps the IPC FIFO from filling up.
    if (head == tail)
        ipc_sendFifoMessage(IPC_CHANNEL_DISPLAY, IPC_DISPLAY_DATA);
    return true;
}

int main()
{
    initializeArm7();

    bool wasConnected = false;
    u32 helloReplies = 0;

    BOOT_STAGE(8);
    while (true)
    {
        SHARED_DISPLAY->mainTick = SHARED_DISPLAY->mainTick + 1;

        // Check for MCU power events.
        if (isDSiMode() && mem_swapByte(false, &sMcuIrqFlag))
        {
            u32 mask = mcu_getIrqMask();
            if (mask & MCU_IRQ_RESET)    { mcu_setWarmBootFlag(true); mcu_hardReset(); }
            if (mask & MCU_IRQ_POWER_OFF){ pmic_shutdown(); }
        }

        // Open means the host has the port open (DTR). Bus suspend doesn't count as closing
        // it: a sleeping PC suspends the bus with the app's port still open, and the DSpico
        // reports an unplugged cable as a suspend too. The ARM9 notices those by the silence.
        bool connected = tud_mounted() && (tud_cdc_get_line_state() & 1);
        SHARED_DISPLAY->usbConnected = connected ? 1 : 0;

        if (wasConnected && !connected)
        {
            // Discard everything from the old session, so the next one starts
            // on a packet boundary even if this one died mid-packet. Packets are
            // word aligned in the ring, so the next one must start on a word too.
            tud_cdc_read_flush();
            tud_cdc_write_clear();
            SHARED_DISPLAY->ringHead = (SHARED_DISPLAY->ringHead + 3) & ~3u;
            SHARED_DISPLAY->ringGeneration = SHARED_DISPLAY->ringGeneration + 1;
        }
        wasConnected = connected;

        if (helloReplies != SHARED_DISPLAY->helloRequests)
        {
            helloReplies = SHARED_DISPLAY->helloRequests;
            tud_cdc_write_str("ds_256x384.v2\n");
            tud_cdc_write_flush();
        }

        if (!fillRing())
            rtos_waitEvent(&sMainWakeEvent, false, true);
    }

    return 0;
}
