#include <string.h>
#include <nds/disc_io.h>
#include <libtwl/rtos/rtosMutex.h>
#include "tusb.h"
#include "UsbStringDescriptor.h"
#include "dsupdate.h"

// The stub is relocated to this address when dlditool patches the ROM. The ARM7
// linker script keeps it free, and the ARM7 owns this WRAM from boot.
#define DLDI_ADDRESS        0x037F8000
#define DLDI_SIZE           (16 * 1024)
#define DLDI_STARTUP        (*(FN_MEDIUM_STARTUP*)(DLDI_ADDRESS + 0x68))
#define DLDI_READ_SECTORS   (*(FN_MEDIUM_READSECTORS*)(DLDI_ADDRESS + 0x70))
#define DLDI_WRITE_SECTORS  (*(FN_MEDIUM_WRITESECTORS*)(DLDI_ADDRESS + 0x74))

#define SECTOR_SIZE         512
#define HOST_NOTICE_TICKS   30   // The host must see the device leave
#define FINISH_TICKS        6    // Time for the eject command's reply to go out

extern rtos_mutex_t gCardMutex;
extern "C" const u8 dsupdate_dldiStub[];

enum { STRID_MANUFACTURER = 1, STRID_PRODUCT, STRID_SERIAL };

static volatile bool sActive;
static volatile bool sEjected;
static volatile u32  sIdleTicks;
static u32 sBlockCount;
static u8  sSector[SECTOR_SIZE] alignas(4);

// Based on https://github.com/asiekierka/nrio-usb-disk/blob/main/source/msc.c by way
// of the dspico-usb-examples mass storage example. The DSpico doesn't report the
// card's size, so this works it out from the first sector.
static u32 findBlockCount()
{
    rtos_lockMutex(&gCardMutex);
    DLDI_READ_SECTORS(0, 1, sSector);
    rtos_unlockMutex(&gCardMutex);

    if (*(u16*)(sSector + 510) != 0xAA55)
        return 0;

    u8 opcode = sSector[0];
    if ((opcode == 0xEB || opcode == 0xE9 || opcode == 0xE8)
        && (!memcmp(sSector + 54, "FAT", 3) || !memcmp(sSector + 82, "FAT32   ", 8)))
    {
        u32 total = *(u32*)(sSector + 32);
        return total < 0x10000 ? (u32)(sSector[19] | (sSector[20] << 8)) : total;
    }

    u32 blockCount = 0;
    for (u32 entry = 0x1BE; entry < 0x1FE; entry += 16)
    {
        const u8* e = sSector + entry;
        u32 start = e[8] | (e[9] << 8) | (e[10] << 16) | ((u32)e[11] << 24);
        u32 count = e[12] | (e[13] << 8) | (e[14] << 16) | ((u32)e[15] << 24);
        if (start + count > blockCount)
            blockCount = start + count;
    }
    return blockCount;
}

bool dsupdate_prepare()
{
    memcpy((void*)DLDI_ADDRESS, dsupdate_dldiStub, DLDI_SIZE);

    rtos_lockMutex(&gCardMutex);
    bool started = DLDI_STARTUP();
    rtos_unlockMutex(&gCardMutex);
    if (!started)
        return false;

    sBlockCount = findBlockCount();
    return sBlockCount != 0;
}

static void reconnect(void (*waitTick)(), bool active)
{
    tud_disconnect();
    for (int i = 0; i < HOST_NOTICE_TICKS; i++)
        waitTick();
    sActive = active;
    tud_connect();
}

void dsupdate_run(void (*waitTick)())
{
    sEjected = false;
    sIdleTicks = 0;
    reconnect(waitTick, true);

    while (!sEjected && sIdleTicks < DSUPDATE_IDLE_TICKS)
    {
        waitTick();
        sIdleTicks = sIdleTicks + 1;
    }

    for (int i = 0; i < FINISH_TICKS; i++)
        waitTick();
    reconnect(waitTick, false);
}

bool dsupdate_active()
{
    return sActive;
}

//--------------------------------------------------------------------
// Descriptors
//--------------------------------------------------------------------

const u8* dsupdate_deviceDescriptor()
{
    static const tusb_desc_device_t descriptor =
    {
        .bLength            = sizeof(tusb_desc_device_t),
        .bDescriptorType    = TUSB_DESC_DEVICE,
        .bcdUSB             = 0x0200,
        .bDeviceClass       = 0,
        .bDeviceSubClass    = 0,
        .bDeviceProtocol    = 0,
        .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
        .idVendor           = DSUPDATE_USB_VID,
        .idProduct          = DSUPDATE_USB_PID,
        .bcdDevice          = 0x0100,
        .iManufacturer      = STRID_MANUFACTURER,
        .iProduct           = STRID_PRODUCT,
        .iSerialNumber      = STRID_SERIAL,
        .bNumConfigurations = 1
    };
    return (const u8*)&descriptor;
}

const u8* dsupdate_configurationDescriptor()
{
    static const u8 descriptor[] =
    {
        TUD_CONFIG_DESCRIPTOR(1, 1, 0, TUD_CONFIG_DESC_LEN + TUD_MSC_DESC_LEN, 0x00, 100),
        TUD_MSC_DESCRIPTOR(0, 0, 0x01, 0x81, 64),
    };
    return descriptor;
}

const u16* dsupdate_stringDescriptor(u8 index)
{
    switch (index)
    {
        case 0:
        {
            static const UsbStringDescriptor<2> descriptor(0x0409);   // English
            return (const u16*)&descriptor;
        }
        case STRID_MANUFACTURER:    return USB_STRING_DESCRIPTOR(u"DSpico");
        case STRID_PRODUCT:         return USB_STRING_DESCRIPTOR(u"DS SD Transfer");
        case STRID_SERIAL:          return USB_STRING_DESCRIPTOR(u"DSPICO001");
        default:                    return nullptr;
    }
}

//--------------------------------------------------------------------
// TinyUSB mass storage callbacks
//--------------------------------------------------------------------

void tud_msc_inquiry_cb(u8 lun, u8 vendorId[8], u8 productId[16], u8 productRev[4])
{
    (void)lun;
    // The host side finds the drive by these. See host/dsupdate.py.
    memcpy(vendorId, "DSpico", 6);
    memcpy(productId, "SD Transfer", 11);
    memcpy(productRev, "1.0", 3);
}

bool tud_msc_test_unit_ready_cb(u8 lun)
{
    if (sEjected)
        tud_msc_set_sense(lun, SCSI_SENSE_NOT_READY, 0x3A, 0x00);   // Medium not present
    return !sEjected;
}

void tud_msc_capacity_cb(u8 lun, u32* blockCount, u16* blockSize)
{
    (void)lun;
    *blockCount = sBlockCount;
    *blockSize = SECTOR_SIZE;
}

bool tud_msc_start_stop_cb(u8 lun, u8 powerCondition, bool start, bool loadEject)
{
    (void)lun;
    (void)powerCondition;
    if (loadEject && !start)
        sEjected = true;
    return true;
}

bool tud_msc_is_writable_cb(u8 lun)
{
    (void)lun;
    return true;
}

int32_t tud_msc_read10_cb(u8 lun, u32 lba, u32 offset, void* buffer, u32 size)
{
    (void)lun;
    if (offset != 0 || size % SECTOR_SIZE != 0)
        return -1;

    sIdleTicks = 0;
    rtos_lockMutex(&gCardMutex);
    DLDI_READ_SECTORS(lba, size / SECTOR_SIZE, buffer);
    rtos_unlockMutex(&gCardMutex);
    return (int32_t)size;
}

int32_t tud_msc_write10_cb(u8 lun, u32 lba, u32 offset, u8* buffer, u32 size)
{
    (void)lun;
    if (offset != 0 || size % SECTOR_SIZE != 0)
        return -1;

    sIdleTicks = 0;
    rtos_lockMutex(&gCardMutex);
    DLDI_WRITE_SECTORS(lba, size / SECTOR_SIZE, buffer);
    rtos_unlockMutex(&gCardMutex);
    return (int32_t)size;
}

int32_t tud_msc_scsi_cb(u8 lun, const u8 command[16], void* buffer, u16 size)
{
    (void)command;
    (void)buffer;
    (void)size;
    tud_msc_set_sense(lun, SCSI_SENSE_ILLEGAL_REQUEST, 0x20, 0x00);   // Invalid command
    return -1;
}
