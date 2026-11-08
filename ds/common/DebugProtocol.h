#pragma once

#include <nds/ndstypes.h>

// Dev channel: the second USB serial port, separate from display data.
// Frames in both directions are a DebugFrameHeader followed by `length`
// payload bytes, little-endian. tools/dsctl.py is the host side.
#define DEBUG_PROTOCOL_VERSION  3
#define DEBUG_FRAME_MAGIC       0x4244  // "DB"

struct DebugFrameHeader
{
    u16 magic;
    u8  op;
    u8  status;
    u32 length;
};
static_assert(sizeof(DebugFrameHeader) == 8);

enum DebugOp : u8
{
    DBG_OP_PING       = 1,    // -> DebugPingReply
    DBG_OP_READ       = 2,    // {u32 address, u32 length} -> memory bytes
    DBG_OP_WRITE      = 3,    // {u32 address, data...} -> empty
    DBG_OP_SCREENSHOT = 4,    // -> 256x384 ABGR1555 pixels
    DBG_OP_BOOT       = 5,    // DebugBootInfo -> empty, then USB disconnects
    DBG_OP_SD_DRIVE   = 6,    // -> empty, then USB swaps to the SD drive until it is ejected
    DBG_OP_LOG        = 0x80, // Unsolicited DS -> host text
};

enum DebugStatus : u8
{
    DBG_STATUS_OK          = 0,
    DBG_STATUS_BAD_REQUEST = 1,
    DBG_STATUS_BAD_CRC     = 2,
    DBG_STATUS_ARM9_DEAD   = 3,
    DBG_STATUS_NO_SD_CARD  = 4,
};

struct DebugPingReply
{
    u32 protocolVersion;
    u32 lastBootCrc;       // CRC of the last pushed ROM; proves a push took effect
    u32 usbBytesReceived;  // Total display bytes written to the ring
    u32 packetCount;       // Display packets parsed
    u32 ringHead;
    u32 ringTail;
    u32 buildNumber;
};

// Segment locations are all in main RAM. Sources are inside the staging area.
struct DebugBootInfo
{
    u32 arm9Source;
    u32 arm9Ram;
    u32 arm9Entry;
    u32 arm9Size;
    u32 arm7Source;
    u32 arm7Ram;
    u32 arm7Entry;
    u32 arm7Size;
    u32 crc32;             // CRC-32 of the ARM9 segment followed by the ARM7 segment
};

// Main RAM layout, above the running app's ARM9 image and below its ARM7 image.
#define DEBUG_STAGING_BASE      0x02200000
#define DEBUG_STAGING_SIZE      0x00140000
#define DEBUG_CAPTURE_BASE      0x02340000
#define DEBUG_CAPTURE_SIZE      (256 * 384 * 2)
#define DEBUG_LAST_BOOT_CRC     (*(vu32*)0x0237FFF0)

#define DEBUG_ARM9_RAM_MIN      0x02000000
#define DEBUG_ARM9_RAM_END      0x02100000   // Display ring starts here
#define DEBUG_ARM7_RAM_MIN      0x02380000

// Reboot handshake on the IPC sync bits. These work with interrupts off and
// need no shared memory, so a crashed ARM9 can still take part.
#define DEBUG_SYNC_REBOOT       0xB   // ARM7: reboot requested
#define DEBUG_SYNC_REBOOT_ACK   0xA   // ARM9: stopped, copying its segment
#define DEBUG_SYNC_ARM7_COPIED  0xC   // ARM7: finished copying its segment

#define DEBUG_LOG_RING_SIZE     8192
