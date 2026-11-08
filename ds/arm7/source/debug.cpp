#include "common.h"
#include <string.h>
#include <libtwl/ipc/ipcFifo.h>
#include <libtwl/ipc/ipcFifoSystem.h>
#include <libtwl/ipc/ipcSync.h>
#include <libtwl/rtos/rtosEvent.h>
#include <libtwl/rtos/rtosIrq.h>
#include <libtwl/rtos/rtosMutex.h>
#include <libtwl/rtos/rtosThread.h>
#include "tusb.h"
#include "device/dcd.h"

#include "BuildId.h"
#include "DisplayProtocol.h"
#include "IpcChannels.h"
#include "debug.h"
#include "dsupdate.h"

// Ticks are VBlanks at most, so these are upper bounds of about 2 s and 0.1 s.
#define TIMEOUT_WAKES       120
#define HOST_NOTICE_WAKES   6

static rtos_thread_t sThread;
static u32 sThreadStack[512];
static rtos_event_t sWake;
static u8 sBuffer[512] alignas(4);

void debug_wake()
{
    rtos_signalEvent(&sWake);
}

static inline void waitWake()
{
    rtos_waitEvent(&sWake, false, true);
}

static bool readExact(void* buffer, u32 length)
{
    u8* dst = (u8*)buffer;
    while (length > 0)
    {
        if (!tud_cdc_n_connected(DEBUG_CDC_ITF))
            return false;

        u32 got = tud_cdc_n_read(DEBUG_CDC_ITF, dst, length);
        dst += got;
        length -= got;
        if (got == 0)
            waitWake();
    }
    return true;
}

static bool writeExact(const void* buffer, u32 length)
{
    const u8* src = (const u8*)buffer;
    while (length > 0)
    {
        if (!tud_cdc_n_connected(DEBUG_CDC_ITF))
            return false;

        u32 sent = tud_cdc_n_write(DEBUG_CDC_ITF, src, length);
        src += sent;
        length -= sent;
        tud_cdc_n_write_flush(DEBUG_CDC_ITF);
        if (sent == 0)
            waitWake();
    }
    return true;
}

static bool sendFrame(u8 op, u8 status, const void* payload, u32 length)
{
    DebugFrameHeader header = { DEBUG_FRAME_MAGIC, op, status, length };
    return writeExact(&header, sizeof(header)) && (length == 0 || writeExact(payload, length));
}

static void discard(u32 length)
{
    while (length > 0)
    {
        u32 part = length < sizeof(sBuffer) ? length : sizeof(sBuffer);
        if (!readExact(sBuffer, part))
            return;
        length -= part;
    }
}

static u32 crc32Update(u32 crc, const u8* data, u32 length)
{
    static const u32 sTable[16] =
    {
        0x00000000, 0x1DB71064, 0x3B6E20C8, 0x26D930AC, 0x76DC4190, 0x6B6B51F4, 0x4DB26158, 0x5005713C,
        0xEDB88320, 0xF00F9344, 0xD6D6A3E8, 0xCB61B38C, 0x9B64C2B0, 0x86D3D2D4, 0xA00AE278, 0xBDBDF21C
    };
    for (u32 i = 0; i < length; i++)
    {
        crc = sTable[(crc ^ data[i]) & 0xF] ^ (crc >> 4);
        crc = sTable[(crc ^ (data[i] >> 4)) & 0xF] ^ (crc >> 4);
    }
    return crc;
}

static bool isInStaging(u32 address, u32 size)
{
    return address >= DEBUG_STAGING_BASE && size <= DEBUG_STAGING_SIZE
        && address - DEBUG_STAGING_BASE <= DEBUG_STAGING_SIZE - size;
}

static bool isBootInfoValid(const DebugBootInfo& info)
{
    return isInStaging(info.arm9Source, info.arm9Size)
        && isInStaging(info.arm7Source, info.arm7Size)
        && info.arm9Ram >= DEBUG_ARM9_RAM_MIN && info.arm9Size <= DEBUG_ARM9_RAM_END - info.arm9Ram
        && info.arm7Ram >= DEBUG_ARM7_RAM_MIN && info.arm7Size <= SHARED_MEM_BASE - info.arm7Ram;
}

static void handleRead(u32 length)
{
    u32 request[2];
    if (length != sizeof(request))
    {
        discard(length);
        sendFrame(DBG_OP_READ, DBG_STATUS_BAD_REQUEST, nullptr, 0);
        return;
    }
    if (readExact(request, sizeof(request)))
        sendFrame(DBG_OP_READ, DBG_STATUS_OK, (const void*)request[0], request[1]);
}

static void handleWrite(u32 length)
{
    u32 address;
    if (length < sizeof(address) || !readExact(&address, sizeof(address)))
    {
        discard(length);
        sendFrame(DBG_OP_WRITE, DBG_STATUS_BAD_REQUEST, nullptr, 0);
        return;
    }

    length -= sizeof(address);
    if (readExact((void*)address, length))
        sendFrame(DBG_OP_WRITE, DBG_STATUS_OK, nullptr, 0);
}

static void handleScreenshot()
{
    u32 startCount = SHARED_DISPLAY->captureCount;
    ipc_sendFifoMessage(IPC_CHANNEL_DISPLAY, IPC_DISPLAY_CAPTURE);
    for (int i = 0; i < TIMEOUT_WAKES && SHARED_DISPLAY->captureCount == startCount; i++)
        waitWake();

    if (SHARED_DISPLAY->captureCount == startCount)
        sendFrame(DBG_OP_SCREENSHOT, DBG_STATUS_ARM9_DEAD, nullptr, 0);
    else
        sendFrame(DBG_OP_SCREENSHOT, DBG_STATUS_OK, (const void*)DEBUG_CAPTURE_BASE, DEBUG_CAPTURE_SIZE);
}

// Volatile keeps the compiler from turning the loop into a memcpy call, which
// could live in the region being overwritten on other link layouts.
static __attribute__((noreturn)) void finishBoot(const DebugBootInfo& info)
{
    volatile u32* src = (volatile u32*)info.arm7Source;
    volatile u32* dst = (volatile u32*)info.arm7Ram;
    for (u32 i = 0; i < (info.arm7Size + 3) / 4; i++)
        dst[i] = src[i];

    const u32 entry = info.arm7Entry;
    ipc_setArm7SyncBits(DEBUG_SYNC_ARM7_COPIED);
    while (ipc_getArm9SyncBits() != 0) { }
    REG_IPCSYNC = 0;

    ((void (*)())entry)();
    while (true) { }
}

static void handleBoot(u32 length)
{
    DebugBootInfo info;
    if (length != sizeof(info))
    {
        discard(length);
        sendFrame(DBG_OP_BOOT, DBG_STATUS_BAD_REQUEST, nullptr, 0);
        return;
    }
    if (!readExact(&info, sizeof(info)))
        return;

    if (!isBootInfoValid(info))
    {
        sendFrame(DBG_OP_BOOT, DBG_STATUS_BAD_REQUEST, nullptr, 0);
        return;
    }

    u32 crc = crc32Update(~0u, (const u8*)info.arm9Source, info.arm9Size);
    crc = ~crc32Update(crc, (const u8*)info.arm7Source, info.arm7Size);
    if (crc != info.crc32)
    {
        sendFrame(DBG_OP_BOOT, DBG_STATUS_BAD_CRC, nullptr, 0);
        return;
    }

    memcpy((void*)&SHARED_DISPLAY->bootInfo, &info, sizeof(info));

    // The ARM9 must answer before USB is torn down, so a dead one fails cleanly.
    ipc_setArm7SyncBits(DEBUG_SYNC_REBOOT);
    for (int i = 0; i < TIMEOUT_WAKES && ipc_getArm9SyncBits() != DEBUG_SYNC_REBOOT_ACK; i++)
        waitWake();

    if (ipc_getArm9SyncBits() != DEBUG_SYNC_REBOOT_ACK)
    {
        ipc_setArm7SyncBits(7);
        sendFrame(DBG_OP_BOOT, DBG_STATUS_ARM9_DEAD, nullptr, 0);
        return;
    }

    sendFrame(DBG_OP_BOOT, DBG_STATUS_OK, nullptr, 0);
    for (int i = 0; i < HOST_NOTICE_WAKES; i++)
        waitWake();

    DEBUG_LAST_BOOT_CRC = info.crc32;

    tud_disconnect();
    for (int i = 0; i < HOST_NOTICE_WAKES; i++)
        waitWake();

    // USB stays initialized on the DSpico: nothing else uses DEINIT followed by
    // INIT, and that sequence left USB dead on hardware. See dcd_init.
    dcd_int_disable(0);
    USB_WARM_BOOT_FLAG = USB_WARM_BOOT_MAGIC;

    // Holding the card mutex means no USB thread is mid-transfer when IRQs stop.
    rtos_lockMutex(&gCardMutex);
    rtos_disableIrqs();
    REG_IME = 0;
    REG_IE = 0;
    REG_IF = ~0u;
    REG_IPCFIFOCNT |= IPCFIFOCNT_SEND_FIFO_CLEAR;   // No stale messages for the new app
    finishBoot(info);
}

static void handleSdDrive()
{
    if (!dsupdate_prepare())
    {
        sendFrame(DBG_OP_SD_DRIVE, DBG_STATUS_NO_SD_CARD, nullptr, 0);
        return;
    }

    sendFrame(DBG_OP_SD_DRIVE, DBG_STATUS_OK, nullptr, 0);
    for (int i = 0; i < HOST_NOTICE_WAKES; i++)
        waitWake();
    dsupdate_run(waitWake);
}

static void drainLog()
{
    volatile SharedDisplayMemory* shared = SHARED_DISPLAY;
    u32 tail = shared->logTail;
    u32 head = shared->logHead;
    if (head == tail || head >= DEBUG_LOG_RING_SIZE || !tud_cdc_n_connected(DEBUG_CDC_ITF))
        return;

    // Up to the end of the ring; a wrapped message arrives as two frames.
    u32 length = (head > tail ? head : DEBUG_LOG_RING_SIZE) - tail;
    if (sendFrame(DBG_OP_LOG, DBG_STATUS_OK, (const void*)&shared->logRing[tail], length))
        shared->logTail = (tail + length) % DEBUG_LOG_RING_SIZE;
}

static void handleFrame(const DebugFrameHeader& header)
{
    switch (header.op)
    {
        case DBG_OP_PING:
        {
            discard(header.length);
            DebugPingReply reply =
            {
                DEBUG_PROTOCOL_VERSION,
                DEBUG_LAST_BOOT_CRC,
                SHARED_DISPLAY->ringHead,
                SHARED_DISPLAY->packetCount,
                SHARED_DISPLAY->ringHead,
                SHARED_DISPLAY->ringTail,
                BUILD_NUMBER,
            };
            sendFrame(DBG_OP_PING, DBG_STATUS_OK, &reply, sizeof(reply));
            break;
        }
        case DBG_OP_READ:       handleRead(header.length);  break;
        case DBG_OP_WRITE:      handleWrite(header.length); break;
        case DBG_OP_SCREENSHOT: discard(header.length); handleScreenshot(); break;
        case DBG_OP_BOOT:       handleBoot(header.length);  break;
        case DBG_OP_SD_DRIVE:   discard(header.length); handleSdDrive(); break;
        default:
            discard(header.length);
            sendFrame(header.op, DBG_STATUS_BAD_REQUEST, nullptr, 0);
            break;
    }
}

static void threadMain(void*)
{
    while (true)
    {
        drainLog();

        if (tud_cdc_n_available(DEBUG_CDC_ITF) < sizeof(DebugFrameHeader))
        {
            waitWake();
            continue;
        }

        DebugFrameHeader header;
        if (!readExact(&header, sizeof(header)))
            continue;

        if (header.magic == DEBUG_FRAME_MAGIC)
            handleFrame(header);
        else
            tud_cdc_n_read_flush(DEBUG_CDC_ITF);   // Lost sync: drop and let the host retry
    }
}

void debug_init()
{
    rtos_createEvent(&sWake);
    // A higher number runs first: above the USB thread (8), below main (16).
    rtos_createThread(&sThread, 12, threadMain, nullptr, sThreadStack, sizeof(sThreadStack));
    rtos_wakeupThread(&sThread);
}
