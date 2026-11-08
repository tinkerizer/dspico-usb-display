#pragma once

#include <nds/ndstypes.h>
#include <stddef.h>
#include "DebugProtocol.h"

#define DISPLAY_WIDTH       256
#define DISPLAY_HEIGHT      384
#define SCREEN_HEIGHT       192   // each physical screen is 192 lines

// Display stream on the first USB serial port. Each packet is a
// DisplayPacketHeader and `length` payload bytes, padded with zeros to a
// multiple of 4 so that packets stay word aligned. Little-endian throughout.
#define DISPLAY_PROTOCOL_VERSION    2
#define DISPLAY_PACKET_MAGIC        0xD5

struct DisplayPacketHeader
{
    u8  magic;
    u8  type;
    u16 reserved;
    u32 length;
};
static_assert(sizeof(DisplayPacketHeader) == 8);

enum DisplayPacketType : u8
{
    DISPLAY_PACKET_HELLO      = 1,  // No payload; the DS replies "ds_256x384.v2\n"
    DISPLAY_PACKET_CLEAR      = 2,  // No payload
    DISPLAY_PACKET_BRIGHTNESS = 3,  // u32 level, 0-100
    DISPLAY_PACKET_POWER      = 4,  // u32 on
    DISPLAY_PACKET_RECT_RAW   = 5,  // u16 x, y, width, height, then ABGR1555 pixels
    DISPLAY_PACKET_RECT_RLE   = 6,  // u16 x, y, width, height, then RLE tokens

    // Reserved: 7 COPY_RECT, 8 FRAME_END.

    // Animations are uploaded once and then play on the DS with no USB traffic.
    DISPLAY_PACKET_ANIM_BEGIN = 0x20,  // u32 slot, u32 frameCount
    DISPLAY_PACKET_ANIM_FRAME = 0x21,  // u32 slot, u32 delay in VBlanks, then a RECT_RLE payload
    DISPLAY_PACKET_ANIM_PLAY  = 0x22,  // u32 slot
    DISPLAY_PACKET_ANIM_STOP  = 0x23,  // u32 slot
    DISPLAY_PACKET_ANIM_RESET = 0x24,  // Stops all animations and frees the store
};

// Animation pixels with bit 15 clear are transparent and show the live picture under them,
// which RECT packets keep updating. Animations are drawn over it.
// Frame 0 of an animation is drawn once. Playback then repeats frames 1 to the
// end, so the last frame should change the picture back to frame 0. A rect with
// width 0 draws nothing and only waits.
#define DISPLAY_ANIM_SLOTS  8

// RECT_RLE tokens are u16s covering the rect row by row:
//   bit 15 set:   the next u16 is a colour, repeated (token & 0x7FFF) + 1 times
//   bit 15 clear: the next token + 1 u16s are literal pixels

// USB data goes straight from the ARM7 into this ring; the ARM9 parses it. Head
// and tail count bytes in total and are masked to index the ring.
#define DISPLAY_RING_BASE   DEBUG_ARM9_RAM_END
#define DISPLAY_RING_SIZE   0x80000
#define DISPLAY_RING_MASK   (DISPLAY_RING_SIZE - 1)

// Uploaded animations live here, just above the ring.
#define DISPLAY_ANIM_BASE   (DISPLAY_RING_BASE + DISPLAY_RING_SIZE)
#define DISPLAY_ANIM_SIZE   0x80000
static_assert(DISPLAY_ANIM_BASE + DISPLAY_ANIM_SIZE <= DEBUG_STAGING_BASE, "Animation store overlaps push staging");

// ARM7 -> ARM9 messages on IPC_CHANNEL_DISPLAY.
enum IpcDisplayCommand : u32
{
    IPC_DISPLAY_DATA    = 1,   // Ring has new data
    IPC_DISPLAY_CAPTURE = 2,   // Copy both screens to DEBUG_CAPTURE_BASE
};

// Shared memory at top of main RAM (64 KB window).
#define SHARED_MEM_BASE     0x023F0000

// Field ownership matters for ARM9 cache coherency: when ARM9 flushes a dirty
// line it writes back the WHOLE 32-byte cache line, so any field the ARM9 writes
// must live in a cache line that the ARM7 never writes.
struct SharedDisplayMemory
{
    // ---- ARM7-owned, bytes 0-63 (ARM9 reads only) ----

    volatile u8  arm7Ready;
    volatile u8  usbConnected;
    u8 _pad0[2];
    volatile u32 ringHead;        // Total bytes written to the ring
    volatile u32 ringGeneration;  // Bumped on disconnect: drop everything up to ringHead
    u8 _pad1[40];
    volatile u32 logTail;         // ARM7 read position in logRing
    volatile u8  bootStage;       // ARM7 startup progress, see BOOT_STAGE
    volatile u8  vblankTick;      // ARM7 IRQs alive
    volatile u8  mainTick;        // ARM7 main loop alive
    volatile u8  usbTick;         // ARM7 USB event thread alive, see USB_EVENT_TICK
    u8 _pad2[4];

    // ---- ARM9-owned cache line (ARM7 reads only) ----

    volatile u32 ringTail;        // Total bytes consumed from the ring
    volatile u8  arm9Ready;
    u8 _pad3[3];
    volatile u32 logHead;         // ARM9 write position in logRing
    volatile u32 captureCount;    // Incremented after each finished screenshot
    volatile u32 helloRequests;   // Incremented for each HELLO packet
    volatile u32 packetCount;
    u8 _pad4[8];

    // Written by ARM9, read by ARM7.
    char logRing[DEBUG_LOG_RING_SIZE];

    // Written by ARM7, read by ARM9. Own cache lines, after everything else.
    DebugBootInfo bootInfo alignas(32);
};

static_assert(offsetof(SharedDisplayMemory, bootStage) == 56, "BOOT_STAGE in arm7/source/common.h must match");
static_assert(offsetof(SharedDisplayMemory, ringTail) == 64, "ARM9-owned fields must start on their own cache line");
static_assert(offsetof(SharedDisplayMemory, logRing) == 96, "logRing must be cache-line aligned");
static_assert(sizeof(SharedDisplayMemory) <= 0x10000, "Shared block must fit its 64 KB window");

#define SHARED_DISPLAY  ((volatile SharedDisplayMemory*)SHARED_MEM_BASE)
