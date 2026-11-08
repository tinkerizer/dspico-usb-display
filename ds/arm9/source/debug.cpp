#include <nds.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <libtwl/ipc/ipcFifo.h>
#include <libtwl/ipc/ipcSync.h>

#include "DisplayProtocol.h"
#include "debug.h"

static void logBytes(const char* text, u32 length)
{
    volatile SharedDisplayMemory* shared = SHARED_DISPLAY;
    DC_InvalidateRange((void*)&shared->logTail, sizeof(u32));
    u32 head = shared->logHead;
    u32 used = (head - shared->logTail) % DEBUG_LOG_RING_SIZE;
    if (length >= DEBUG_LOG_RING_SIZE - 1 - used)
        return;

    char* ring = (char*)shared->logRing;
    for (u32 i = 0; i < length; i++)
    {
        ring[head] = text[i];
        head = (head + 1) % DEBUG_LOG_RING_SIZE;
    }
    DC_FlushRange(ring, DEBUG_LOG_RING_SIZE);

    shared->logHead = head;
    DC_FlushRange((void*)&shared->logHead, sizeof(u32));
}

void debug_log(const char* format, ...)
{
    char text[192];
    va_list args;
    va_start(args, format);
    int length = vsnprintf(text, sizeof(text), format, args);
    va_end(args);
    if (length > 0)
        logBytes(text, (u32)length < sizeof(text) ? (u32)length : sizeof(text) - 1);
}

void debug_capture(const void* topScreen, const void* bottomScreen)
{
    // DMA writes main RAM directly, and the ARM9 never caches this region.
    dmaCopyWords(3, topScreen, (void*)DEBUG_CAPTURE_BASE, 256 * 192 * 2);
    dmaCopyWords(3, bottomScreen, (void*)(DEBUG_CAPTURE_BASE + 256 * 192 * 2), 256 * 192 * 2);

    SHARED_DISPLAY->captureCount = SHARED_DISPLAY->captureCount + 1;
    DC_FlushRange((void*)&SHARED_DISPLAY->captureCount, sizeof(u32));
}

// Runs from ITCM because it overwrites the app in main RAM, so it can't call
// anything there. noinline keeps it out of reboot(), which is in main RAM, and
// volatile keeps the compiler from turning the loop into memcpy.
static ITCM_CODE __attribute__((noreturn, noinline)) void bootFromItcm(u32 source, u32 ram, u32 size, u32 entry)
{
    u32 control;
    asm volatile("mrc p15, 0, %0, c1, c0, 0" : "=r"(control));
    control &= ~((1u << 2) | (1u << 12));   // D-cache and I-cache off
    asm volatile("mcr p15, 0, %0, c1, c0, 0" :: "r"(control));
    asm volatile("mcr p15, 0, %0, c7, c5, 0" :: "r"(0));   // Invalidate I-cache
    asm volatile("mcr p15, 0, %0, c7, c6, 0" :: "r"(0));   // Invalidate D-cache

    volatile u32* src = (volatile u32*)source;
    volatile u32* dst = (volatile u32*)ram;
    for (u32 i = 0; i < (size + 3) / 4; i++)
        dst[i] = src[i];

    while ((REG_IPCSYNC & IPCSYNC_REMOTE_DATA_MASK) != DEBUG_SYNC_ARM7_COPIED) { }
    REG_IPCSYNC = 0;

    ((void (*)())entry)();
    while (true) { }
}

static void __attribute__((noreturn)) reboot()
{
    REG_IME = 0;
    REG_IE = 0;
    REG_IF = ~0u;
    REG_IPCFIFOCNT |= IPCFIFOCNT_SEND_FIFO_CLEAR;   // No stale messages for the new app
    for (int channel = 0; channel < 4; channel++)
        DMA_CR(channel) = 0;

    DC_InvalidateRange((void*)&SHARED_DISPLAY->bootInfo, sizeof(DebugBootInfo));
    const u32 source = SHARED_DISPLAY->bootInfo.arm9Source;
    const u32 ram    = SHARED_DISPLAY->bootInfo.arm9Ram;
    const u32 size   = SHARED_DISPLAY->bootInfo.arm9Size;
    const u32 entry  = SHARED_DISPLAY->bootInfo.arm9Entry;

    DC_FlushAll();
    ipc_setArm9SyncBits(DEBUG_SYNC_REBOOT_ACK);
    bootFromItcm(source, ram, size, entry);
}

void debug_checkReboot()
{
    if (ipc_getArm7SyncBits() == DEBUG_SYNC_REBOOT)
        reboot();
}

// Reports the crash, then waits so a fixed build can still be pushed: the ARM7
// keeps USB alive and this loop answers the reboot request.
static void crashHandler()
{
    debug_log("ARM9 CRASH pc=%08lX lr=%08lX sp=%08lX\n",
        (u32)exceptionRegisters[15], (u32)exceptionRegisters[14], (u32)exceptionRegisters[13]);
    for (int i = 0; i < 13; i += 4)
    {
        debug_log("  r%-2d %08lX %08lX %08lX %08lX\n", i, (u32)exceptionRegisters[i],
            (u32)exceptionRegisters[i + 1], (u32)exceptionRegisters[i + 2], (u32)exceptionRegisters[i + 3]);
    }
    while (true)
        debug_checkReboot();
}

void debug_init()
{
    setExceptionHandler(crashHandler);
}
