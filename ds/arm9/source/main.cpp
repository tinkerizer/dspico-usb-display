#include <nds.h>
#include <stdio.h>
#include <string.h>
#include <nds/ndstypes.h>
#include <libtwl/gfx/gfxStatus.h>
#include <libtwl/mem/memExtern.h>
#include <libtwl/mem/memSwap.h>
#include <libtwl/rtos/rtosIrq.h>
#include <libtwl/rtos/rtosThread.h>
#include <libtwl/rtos/rtosEvent.h>
#include <libtwl/ipc/ipcSync.h>
#include <libtwl/ipc/ipcFifoSystem.h>
#include <libtwl/gfx/gfx.h>
#include <libtwl/dma/dmaTwl.h>
#include <libtwl/mem/memVram.h>

#include "BuildId.h"
#include "DisplayProtocol.h"
#include "IpcChannels.h"
#include "debug.h"

//--------------------------------------------------------------------
// Hardware registers
//--------------------------------------------------------------------

#define VRAM_A_BASE         0x06800000
// VRAM C mapped as sub BG (MST=4, VRAMCNT_C=0x84) appears at 0x06200000.
// This is BG_GFX_SUB in libnds — the sub engine BG graphics base address.
#define VRAM_C_SUB_BG_BASE  0x06200000

#define REG_DISPCNT         (*(vu32*)0x04000000)
#define REG_POWCNT          (*(vu16*)0x04000304)
#define POWER_LCD_TOP       (1 << 0)
#define POWER_LCD_BOTTOM    (1 << 1)
#define POWER_2D_A          (1 << 1)
#define POWER_2D_B          (1 << 9)
#define POWER_SWAP_LCDS     (1 << 15)

#define REG_VRAMCNT_A       (*(vu8*)0x04000240)
#define VRAM_ENABLE         0x80
#define VRAM_A_LCD          0x00

#define REG_MASTER_BRIGHT       (*(vu16*)0x0400006C)
#define REG_MASTER_BRIGHT_SUB   (*(vu16*)0x0400106C)

static vu16* const gTopScreen = (vu16*)VRAM_A_BASE;
static vu16* const gBotScreen = (vu16*)VRAM_C_SUB_BG_BASE;

//--------------------------------------------------------------------
// Events & counters
//--------------------------------------------------------------------

static rtos_event_t sWakeEvent;      // Signalled by new ring data and by VBlank

// Set in IRQ context, consumed by the main loop, because DMA in IRQ context
// would race the blit DMA.
static volatile u8 sPendingCapture = 0;

//--------------------------------------------------------------------
// IPC handler — called in IRQ context: set a flag, wake the main loop.
//--------------------------------------------------------------------

static void displayIpcHandler(u32 channel, u32 data, void* arg)
{
    (void)channel; (void)arg;

    if (data == IPC_DISPLAY_CAPTURE)
        sPendingCapture = 1;
    rtos_signalEvent(&sWakeEvent);
}

//--------------------------------------------------------------------
// Display helpers
//--------------------------------------------------------------------

// Apply a 0-100 brightness level to BOTH screens via master brightness.
static void applyBrightness(u8 level)
{
    u16 value;
    if (level == 0)
        value = (2 << 14) | 16;       // subtract 16 steps = fully dark
    else if (level >= 100)
        value = 0;                    // no fade = full brightness
    else
        value = (2 << 14) | (u16)(16 - (level * 16 / 100));
    REG_MASTER_BRIGHT     = value;
    REG_MASTER_BRIGHT_SUB = value;
}

// The live picture from the host, and which animation, if any, is drawn over each pixel.
// Live pixels reach the screen only where no animation covers them, and an animation
// pixel that turns transparent shows the live one again.
static u16 sBase[DISPLAY_WIDTH * DISPLAY_HEIGHT] alignas(32);
static u8 sCover[DISPLAY_WIDTH * DISPLAY_HEIGHT];    // Animation slot + 1, or 0
static u16 sCoverRows[DISPLAY_HEIGHT];               // Covered pixels per row, so most rows skip the check

static inline vu16* screenPixel(u32 index)
{
    const u32 y = index >> 8;
    return (y < SCREEN_HEIGHT ? gTopScreen : gBotScreen - SCREEN_HEIGHT * 256) + index;
}

static inline void putLive(u32 index, u16 color)
{
    sBase[index] = color;
    if (!sCover[index])
        *screenPixel(index) = color;
}

// Bit 15 clear is a transparent pixel.
static inline void putAnim(u32 index, u16 color, u8 owner)
{
    if (color & 0x8000)
    {
        if (!sCover[index])
            sCoverRows[index >> 8]++;
        sCover[index] = owner;
        *screenPixel(index) = color;
    }
    else if (sCover[index] == owner)
    {
        sCover[index] = 0;
        sCoverRows[index >> 8]--;
        *screenPixel(index) = sBase[index];
    }
}

// Shows the live picture again wherever an animation (or with 0, any) was drawn.
static void uncover(u8 owner)
{
    for (u32 index = 0; index < DISPLAY_WIDTH * DISPLAY_HEIGHT; index++)
    {
        if (sCover[index] && (owner == 0 || sCover[index] == owner))
        {
            sCover[index] = 0;
            sCoverRows[index >> 8]--;
            *screenPixel(index) = sBase[index];
        }
    }
}

static void clearScreens()
{
    dmaFillWords(0x80008000, (void*)VRAM_A_BASE, 256 * 192 * 2);
    dmaFillWords(0x80008000, (void*)VRAM_C_SUB_BG_BASE, 256 * 192 * 2);
    for (u16& pixel : sBase)
        pixel = 0x8000;
    memset(sCover, 0, sizeof(sCover));
    memset(sCoverRows, 0, sizeof(sCoverRows));
}

static void initializeDisplay()
{
    REG_POWCNT = POWER_LCD_TOP | POWER_LCD_BOTTOM | POWER_2D_A | POWER_2D_B | POWER_SWAP_LCDS;

    // Engine A (top screen): VRAM bank A in LCD/framebuffer mode.
    REG_VRAMCNT_A = VRAM_ENABLE | VRAM_A_LCD;
    REG_DISPCNT = (2 << 16) | (0 << 18);   // VRAM display mode, bank A

    // Engine B (bottom screen): the sub engine does NOT support direct VRAM
    // framebuffer display.  Use BG bitmap mode instead:
    //   - Map VRAM C as sub BG (MST=4) → accessible at 0x06200000
    //   - Set sub engine to mode 5 (supports extended/affine BGs with BgType_Bmp16)
    //   - Init BG3 as a 256×256 16-bit bitmap layer
    // videoSetModeSub does a full register write so it clears any BG active bits
    // left by consoleDemoInit (BG0 text mode).
    // Pixels with bit 15 = 0 are transparent; we fill with 0x8000 (black, opaque).
    vramSetBankC(VRAM_C_SUB_BG);
    videoSetModeSub(MODE_5_2D);
    bgInitSub(3, BgType_Bmp16, BgSize_B16_256x256, 0, 0);

    // Clear both screens to black (opaque).
    dmaFillWords(0x80008000, (void*)VRAM_A_BASE, 256 * 192 * 2);
    dmaFillWords(0x80008000, (void*)VRAM_C_SUB_BG_BASE, 256 * 192 * 2);
    REG_MASTER_BRIGHT = 0;
    REG_MASTER_BRIGHT_SUB = 0;
}

//--------------------------------------------------------------------
// Display stream parser
//--------------------------------------------------------------------

enum class ParseState { Header, Body, RectHeader, RectRows, RectRle, AnimFrame, Skip };

// Read through the uncached mirror: the ARM7 writes this memory directly.
static const vu8* const sRing = (const vu8*)memUncached((void*)DISPLAY_RING_BASE);

static ParseState sParseState = ParseState::Header;
static u32 sTail = 0;         // Total bytes consumed
static u32 sPacketEnd = 0;    // Total bytes at the end of the current packet, with padding
static u32 sPayloadLength = 0;
static u8  sPacketType = 0;
static u16 sRectX, sRectY, sRectWidth, sRectHeight, sRectRow;

static u8 sBrightness = 100;
static bool sScreenOn = true;

static inline u8 ringU8(u32 position)
{
    return sRing[position & DISPLAY_RING_MASK];
}

static inline u16 ringU16(u32 position)
{
    return ringU8(position) | (ringU8(position + 1) << 8);
}

static inline u32 ringU32(u32 position)
{
    return ringU16(position) | (ringU16(position + 2) << 16);
}

static void publishTail()
{
    SHARED_DISPLAY->ringTail = sTail;
    DC_FlushRange((void*)&SHARED_DISPLAY->ringTail, sizeof(u32));
}

// Copies one rect row from the ring to VRAM. Rows outside the screen are dropped.
static void blitRow(u32 position, u16 x, u16 y, u16 width)
{
    if (y >= DISPLAY_HEIGHT || x >= DISPLAY_WIDTH)
        return;

    u16 w = x + width > DISPLAY_WIDTH ? DISPLAY_WIDTH - x : width;
    const u32 index = y * DISPLAY_WIDTH + x;
    const vu16* ring = (const vu16*)sRing;
    if (sCoverRows[y])
    {
        for (u16 i = 0; i < w; i++)
            putLive(index + i, ring[((position + i * 2) & DISPLAY_RING_MASK) >> 1]);
        return;
    }
    for (u16 i = 0; i < w; i++)
        sBase[index + i] = ring[((position + i * 2) & DISPLAY_RING_MASK) >> 1];

    vu16* dst = y < SCREEN_HEIGHT
        ? gTopScreen + y * 256 + x
        : gBotScreen + (y - SCREEN_HEIGHT) * 256 + x;

    const u32 offset = position & DISPLAY_RING_MASK;
    const u32 src = DISPLAY_RING_BASE + offset;
    const u32 bytes = w * 2u;

    // Word DMA ignores the low address bits and truncates the length to whole
    // words, so odd positions and widths need halfword DMA. DMA bypasses the
    // ARM9 cache, so it sees what the ARM7 wrote.
    if (w < 16 || offset + bytes > DISPLAY_RING_SIZE)
    {
        for (u16 i = 0; i < w; i++)
            dst[i] = ringU16(position + i * 2);
    }
    else if (((src | (u32)dst | bytes) & 3) == 0)
    {
        dmaCopyWords(3, (const void*)src, (void*)dst, bytes);
    }
    else
    {
        dmaCopyHalfWords(3, (const void*)src, (void*)dst, bytes);
    }
}

// Tracks where the next RLE pixel goes within its rect. Owner 0 is the live picture,
// and otherwise the animation slot + 1.
struct RectCursor
{
    u16 x, y, left, right, bottom;
    u8 owner;

    inline void put(u16 color)
    {
        if (y < bottom)
        {
            if (x < DISPLAY_WIDTH && y < DISPLAY_HEIGHT)
            {
                if (owner)
                    putAnim(y * DISPLAY_WIDTH + x, color, owner);
                else
                    putLive(y * DISPLAY_WIDTH + x, color);
            }
            if (++x == right)
            {
                x = left;
                y++;
            }
        }
    }
};

// Draws a RECT_RLE payload. `read` returns the u16 at a byte position.
template <typename Read>
static void decodeRle(Read read, u32 position, u32 end, u8 owner = 0)
{
    const u16 x = read(position);
    const u16 y = read(position + 2);
    const u16 width = read(position + 4);
    const u16 height = read(position + 6);
    position += 8;
    if (width == 0 || width > DISPLAY_WIDTH)
        return;

    RectCursor cursor = { x, y, x, (u16)(x + width), (u16)(y + height), owner };
    while (position + 2 <= end)
    {
        u16 token = read(position);
        position += 2;
        u32 count = (token & 0x7FFF) + 1;
        if (token & 0x8000)
        {
            u16 color = read(position);
            position += 2;
            for (u32 i = 0; i < count; i++)
                cursor.put(color);
        }
        else
        {
            for (u32 i = 0; i < count && position + 2 <= end; i++, position += 2)
                cursor.put(read(position));
        }
    }
}

// The whole packet is in the ring by now, and every position is word aligned.
static void decodeRingRle(u32 position, u32 end)
{
    const vu16* ring = (const vu16*)sRing;
    decodeRle([ring](u32 at) -> u16 { return ring[(at & DISPLAY_RING_MASK) >> 1]; }, position, end);
}

//--------------------------------------------------------------------
// Animation player
//--------------------------------------------------------------------

// Stored frames: u32 body size, u32 delay in VBlanks, then the RLE body, padded
// to 4 bytes.
struct Animation
{
    u32 frameCount;
    u32 framesLoaded;
    u32 firstFrame;     // Store offsets
    u32 secondFrame;
    u32 nextFrame;
    u32 nextIndex;
    u32 dueVBlank;
    bool playing;
};

static Animation sAnimations[DISPLAY_ANIM_SLOTS];
static u32 sAnimStoreUsed = 0;
static vu32 sVBlankCount = 0;
static u8* const sAnimStore = (u8*)DISPLAY_ANIM_BASE;

static void resetAnimations()
{
    memset(sAnimations, 0, sizeof(sAnimations));
    sAnimStoreUsed = 0;
}

static inline u32 frameSize(u32 offset)
{
    return 8 + ((*(u32*)(sAnimStore + offset) + 3) & ~3u);
}

// Draws the frame at `offset` for a slot and returns its delay.
static u32 drawAnimFrame(u32 offset, u32 slot)
{
    const u32 bodySize = *(u32*)(sAnimStore + offset);
    const u32 delay = *(u32*)(sAnimStore + offset + 4);
    const u8* body = sAnimStore + offset + 8;
    decodeRle([body](u32 at) -> u16 { return *(const u16*)(body + at); }, 0, bodySize, (u8)(slot + 1));
    return delay ? delay : 1;
}

static void storeAnimFrame(u32 position, u32 length)
{
    const u32 slot = ringU32(position);
    const u32 delay = ringU32(position + 4);
    const u32 bodySize = length - 8;
    const u32 size = 8 + ((bodySize + 3) & ~3u);
    if (slot >= DISPLAY_ANIM_SLOTS || sAnimations[slot].framesLoaded >= sAnimations[slot].frameCount)
        return;
    if (size > DISPLAY_ANIM_SIZE - sAnimStoreUsed)
    {
        debug_log("Animation store full, dropping slot %lu\n", slot);
        sAnimations[slot].frameCount = 0;
        return;
    }

    Animation& animation = sAnimations[slot];
    u32* header = (u32*)(sAnimStore + sAnimStoreUsed);
    header[0] = bodySize;
    header[1] = delay;
    u8* body = sAnimStore + sAnimStoreUsed + 8;
    for (u32 i = 0; i < bodySize; i++)
        body[i] = ringU8(position + 8 + i);

    if (animation.framesLoaded == 0)
        animation.firstFrame = sAnimStoreUsed;
    else if (animation.framesLoaded == 1)
        animation.secondFrame = sAnimStoreUsed;
    animation.framesLoaded++;
    sAnimStoreUsed += size;
}

static void playAnimation(u32 slot)
{
    if (slot >= DISPLAY_ANIM_SLOTS)
        return;

    Animation& animation = sAnimations[slot];
    if (animation.frameCount == 0 || animation.framesLoaded != animation.frameCount)
        return;

    animation.dueVBlank = sVBlankCount + drawAnimFrame(animation.firstFrame, slot);
    animation.nextFrame = animation.secondFrame;
    animation.nextIndex = 1;
    animation.playing = animation.frameCount > 1;
}

// Runs from the main loop, which VBlank wakes, so frames usually land in VBlank.
static void updateAnimations()
{
    const u32 now = sVBlankCount;
    for (u32 slot = 0; slot < DISPLAY_ANIM_SLOTS; slot++)
    {
        Animation& animation = sAnimations[slot];
        if (!animation.playing || (s32)(now - animation.dueVBlank) < 0)
            continue;

        const u32 offset = animation.nextFrame;
        animation.dueVBlank = now + drawAnimFrame(offset, slot);
        if (++animation.nextIndex == animation.frameCount)
        {
            animation.nextIndex = 1;
            animation.nextFrame = animation.secondFrame;
        }
        else
        {
            animation.nextFrame = offset + frameSize(offset);
        }
    }
}

static void handleSmallPacket()
{
    switch (sPacketType)
    {
        case DISPLAY_PACKET_HELLO:
            SHARED_DISPLAY->helloRequests = SHARED_DISPLAY->helloRequests + 1;
            DC_FlushRange((void*)&SHARED_DISPLAY->helloRequests, sizeof(u32));
            break;
        case DISPLAY_PACKET_CLEAR:
            clearScreens();
            break;
        case DISPLAY_PACKET_BRIGHTNESS:
            if (sPayloadLength >= 4)
            {
                sBrightness = (u8)ringU32(sTail);
                applyBrightness(sScreenOn ? sBrightness : 0);
            }
            break;
        case DISPLAY_PACKET_POWER:
            if (sPayloadLength >= 4)
            {
                sScreenOn = ringU32(sTail) != 0;
                applyBrightness(sScreenOn ? sBrightness : 0);
            }
            break;
        case DISPLAY_PACKET_ANIM_BEGIN:
            if (sPayloadLength >= 8 && ringU32(sTail) < DISPLAY_ANIM_SLOTS)
            {
                Animation& animation = sAnimations[ringU32(sTail)];
                memset(&animation, 0, sizeof(animation));
                uncover((u8)(ringU32(sTail) + 1));
                animation.frameCount = ringU32(sTail + 4);
            }
            break;
        case DISPLAY_PACKET_ANIM_PLAY:
            if (sPayloadLength >= 4)
                playAnimation(ringU32(sTail));
            break;
        case DISPLAY_PACKET_ANIM_STOP:
            if (sPayloadLength >= 4 && ringU32(sTail) < DISPLAY_ANIM_SLOTS)
                sAnimations[ringU32(sTail)].playing = false;
            break;
        case DISPLAY_PACKET_ANIM_RESET:
            resetAnimations();
            uncover(0);
            break;
    }
}

// Consumes as much of the ring as possible. Partial data waits for the next call.
static void drainRing()
{
    const u32 head = SHARED_DISPLAY->ringHead;
    while (true)
    {
        const u32 available = head - sTail;
        switch (sParseState)
        {
            case ParseState::Header:
            {
                if (available < sizeof(DisplayPacketHeader))
                {
                    publishTail();
                    return;
                }
                if (ringU8(sTail) != DISPLAY_PACKET_MAGIC)
                {
                    sTail += 4;     // Packets are word aligned: look for the next one
                    break;
                }

                sPacketType = ringU8(sTail + 1);
                sPayloadLength = ringU32(sTail + 4);
                sTail += sizeof(DisplayPacketHeader);
                sPacketEnd = sTail + ((sPayloadLength + 3) & ~3u);
                SHARED_DISPLAY->packetCount = SHARED_DISPLAY->packetCount + 1;

                if (sPacketType == DISPLAY_PACKET_RECT_RAW)
                    sParseState = ParseState::RectHeader;
                else if (sPacketType == DISPLAY_PACKET_RECT_RLE && sPayloadLength >= 8
                    && sPayloadLength <= DISPLAY_RING_SIZE / 2)
                    sParseState = ParseState::RectRle;
                else if (sPacketType == DISPLAY_PACKET_ANIM_FRAME && sPayloadLength >= 16
                    && sPayloadLength <= DISPLAY_RING_SIZE / 2)
                    sParseState = ParseState::AnimFrame;
                else if (sPayloadLength <= 64)
                    sParseState = ParseState::Body;
                else
                    sParseState = ParseState::Skip;
                break;
            }
            case ParseState::Body:
            {
                if ((s32)(head - sPacketEnd) < 0)
                {
                    publishTail();
                    return;
                }
                handleSmallPacket();
                sTail = sPacketEnd;
                sParseState = ParseState::Header;
                break;
            }
            case ParseState::RectHeader:
            {
                if (available < 8)
                {
                    publishTail();
                    return;
                }
                sRectX = ringU16(sTail);
                sRectY = ringU16(sTail + 2);
                sRectWidth = ringU16(sTail + 4);
                sRectHeight = ringU16(sTail + 6);
                sRectRow = 0;
                sTail += 8;

                bool valid = sRectWidth > 0 && sRectWidth <= DISPLAY_WIDTH
                    && sPayloadLength == 8u + (u32)sRectWidth * sRectHeight * 2;
                sParseState = valid ? ParseState::RectRows : ParseState::Skip;
                break;
            }
            case ParseState::RectRows:
            {
                const u32 rowBytes = sRectWidth * 2u;
                while (sRectRow < sRectHeight && head - sTail >= rowBytes)
                {
                    blitRow(sTail, sRectX, sRectY + sRectRow, sRectWidth);
                    sTail += rowBytes;
                    sRectRow++;
                    if ((sRectRow & 31) == 0)
                        publishTail();  // Free ring space during big rects
                }
                if (sRectRow < sRectHeight)
                {
                    publishTail();
                    return;
                }
                sParseState = ParseState::Skip;
                break;
            }
            case ParseState::RectRle:
            {
                if ((s32)(head - sPacketEnd) < 0)
                {
                    publishTail();
                    return;
                }
                decodeRingRle(sTail, sTail + sPayloadLength);
                sTail = sPacketEnd;
                sParseState = ParseState::Header;
                break;
            }
            case ParseState::AnimFrame:
            {
                if ((s32)(head - sPacketEnd) < 0)
                {
                    publishTail();
                    return;
                }
                storeAnimFrame(sTail, sPayloadLength);
                sTail = sPacketEnd;
                sParseState = ParseState::Header;
                break;
            }
            case ParseState::Skip:
            {
                if ((s32)(head - sPacketEnd) < 0)
                {
                    sTail = head;
                    publishTail();
                    return;
                }
                sTail = sPacketEnd;
                sParseState = ParseState::Header;
                break;
            }
        }
    }
}

//--------------------------------------------------------------------
// VBlank & connection feedback
//--------------------------------------------------------------------

static bool  gConnected    = false;
static u32   gFrameCounter = 0;

static void vblankIrq(u32)
{
    sVBlankCount = sVBlankCount + 1;

    // Wake the main loop every frame so USB connect/disconnect is checked
    // and so we don't block forever if an IPC signal was missed.
    rtos_signalEvent(&sWakeEvent);

    // Checked here, not in the main loop, so a hung main loop can still reboot.
    debug_checkReboot();
}

static void drawSquare(int x, int y, u16 color)
{
    for (int py = y; py < y + 6; py++)
        for (int px = x; px < x + 6; px++)
            gTopScreen[py * 256 + px] = color;
}

// 3x5 digits, one row per 3 low bits, top row first.
static const u16 sDigits[10] =
{
    0x7B6F, 0x2C97, 0x73E7, 0x73CF, 0x5BC9, 0x79CF, 0x79EF, 0x7292, 0x7BEF, 0x7BCF
};

static void drawDigit(int x, int y, int digit, u16 color)
{
    for (int row = 0; row < 5; row++)
    {
        for (int column = 0; column < 3; column++)
        {
            bool lit = (sDigits[digit] >> ((4 - row) * 3 + (2 - column))) & 1;
            for (int py = 0; py < 2; py++)
                for (int px = 0; px < 2; px++)
                    gTopScreen[(y + row * 2 + py) * 256 + x + column * 2 + px] = lit ? color : (u16)0x8000;
        }
    }
}

static void drawBuildNumber(int x, int y, u16 color)
{
    u32 number = BUILD_NUMBER;
    int digits = 1;
    for (u32 n = number; n >= 10; n /= 10)
        digits++;
    for (int i = digits - 1; i >= 0; i--, number /= 10)
        drawDigit(x + i * 8, y, number % 10, color);
}

// Startup diagnostics while no host is connected. Magenta marks this build, white
// squares count ARM7 boot stages (8 = reached the main loop), and the number below
// is the build number. Nothing here flashes.
static void drawBootDiagnostics()
{
    const u16 magenta = 0x8000 | (31 << 10) | 31;
    const u16 white   = 0xFFFF;
    const u16 black   = 0x8000;

    drawSquare(16, 8, magenta);
    for (int stage = 1; stage <= 8; stage++)
        drawSquare(16 + stage * 10, 8, stage <= SHARED_DISPLAY->bootStage ? white : black);
    drawBuildNumber(46, 20, white);
}

//--------------------------------------------------------------------
// Main
//--------------------------------------------------------------------

int main(int argc, char* argv[])
{
    mem_setDsCartridgeCpu(EXMEMCNT_SLOT1_CPU_ARM7);

    rtos_initIrq();
    rtos_startMainThread();
    ipc_initFifoSystem();

    rtos_createEvent(&sWakeEvent);

    // Console on bottom screen for boot messages only — before display takeover.
    consoleDemoInit();
    printf("DS Display ARM9\n");
    printf("Waiting for ARM7...\n");

    while (ipc_getArm7SyncBits() != 7) { }
    printf("ARM7 ready\n");

    // Register IPC handler BEFORE signalling ARM9 ready.
    ipc_setChannelHandler(IPC_CHANNEL_DISPLAY, displayIpcHandler, nullptr);

    SHARED_DISPLAY->arm9Ready = 1;
    DC_FlushRange((void*)&SHARED_DISPLAY->arm9Ready, sizeof(u8));
    ipc_setArm9SyncBits(6);

    // Take over display hardware — no more printf after this point.
    initializeDisplay();
    debug_init();
    debug_log("ARM9 started\n");

    // VBlank IRQ — purely for keepalive/connection polling.
    rtos_setIrqFunc(RTOS_IRQ_VBLANK, vblankIrq);
    rtos_enableIrqMask(RTOS_IRQ_VBLANK);
    gfx_setVBlankIrqEnabled(true);

    u32 generation = 0;

    while (true)
    {
        // Wait for ring data or the VBlank keepalive (auto-clear).
        rtos_waitEvent(&sWakeEvent, false, true);

        // ARM7-owned shared fields are read through the cache, so refresh them.
        DC_InvalidateRange((void*)SHARED_MEM_BASE, offsetof(SharedDisplayMemory, logRing));

        if (generation != SHARED_DISPLAY->ringGeneration)
        {
            // The host went away: anything before this head belongs to it.
            generation = SHARED_DISPLAY->ringGeneration;
            sTail = SHARED_DISPLAY->ringHead;
            sParseState = ParseState::Header;
            publishTail();
            resetAnimations();
        }

        drainRing();
        updateAnimations();

        if (mem_swapByte(false, &sPendingCapture))
            debug_capture((const void*)VRAM_A_BASE, (const void*)VRAM_C_SUB_BG_BASE);

        // Connection housekeeping.
        gFrameCounter++;
        bool connected = SHARED_DISPLAY->usbConnected != 0;
        if (!gConnected && connected)
        {
            // Just connected: clear screens and restore the last brightness
            // the host configured (100 until the host sets one).
            clearScreens();
            applyBrightness(sScreenOn ? sBrightness : 0);
        }
        else if (gConnected && !connected)
        {
            // Just disconnected (or app closed COM port): black out both screens
            // and dim backlights to minimum.
            // Use 0x8000 (opaque black) — bit15=0 is transparent in sub BG mode.
            clearScreens();
            applyBrightness(0);
        }
        gConnected = connected;
        if (!gConnected)
            drawBootDiagnostics();
    }

    return 0;
}
