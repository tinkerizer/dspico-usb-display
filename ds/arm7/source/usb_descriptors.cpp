#include "common.h"
#include "tusb.h"
#include "usb_descriptors.h"
#include "../common/DisplayProtocol.h"
#include "UsbStringDescriptor.h"
#include "dsupdate.h"


//--------------------------------------------------------------------
// Device Descriptor
//--------------------------------------------------------------------

const u8* tud_descriptor_device_cb(void)
{
    if (dsupdate_active())
        return dsupdate_deviceDescriptor();

    static const tusb_desc_device_t deviceDescriptor =
    {
        .bLength            = sizeof(tusb_desc_device_t),
        .bDescriptorType    = TUSB_DESC_DEVICE,
        .bcdUSB             = 0x0200,  // USB 2.0

        // Use IAD (Interface Association Descriptor) device-level class codes.
        // Required for multi-interface CDC-ACM so the host correctly associates
        // the communication + data interface pair and loads the right driver.
        .bDeviceClass       = TUSB_CLASS_MISC,
        .bDeviceSubClass    = MISC_SUBCLASS_COMMON,
        .bDeviceProtocol    = MISC_PROTOCOL_IAD,
        .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,

        .idVendor           = USB_VID,
        .idProduct          = USB_PID,
        .bcdDevice          = 0x0200,  // Bumped so Windows re-reads the descriptors

        .iManufacturer      = STRID_MANUFACTURER,
        .iProduct           = STRID_PRODUCT,
        .iSerialNumber      = STRID_SERIAL,

        .bNumConfigurations = 0x01
    };

    return (const u8*)&deviceDescriptor;
}

//--------------------------------------------------------------------
// Configuration Descriptor
//--------------------------------------------------------------------

#define CONFIG_TOTAL_LEN    (TUD_CONFIG_DESC_LEN + 2 * TUD_CDC_DESC_LEN)

const u8* tud_descriptor_configuration_cb(u8 index)
{
    (void)index;

    if (dsupdate_active())
        return dsupdate_configurationDescriptor();

    static const u8 configurationDescriptor[] =
    {
        // Config number, interface count, string index, total length, attribute, power in mA
        TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),

        // CDC: Interface number, string index, EP notification address and size, EP data address (out, in) and size
        TUD_CDC_DESCRIPTOR(
            ITF_NUM_CDC,
            STRID_CDC_INTERFACE,
            0x80 | EPNUM_CDC_NOTIF, 8,          // Notification EP (IN)
            EPNUM_CDC_OUT, 0x80 | EPNUM_CDC_IN, // Data EPs (OUT, IN)
            64                                  // wMaxPacketSize: full-speed bulk is
                                                // always 64; the (larger) transfer
                                                // size is CFG_TUD_CDC_EP_BUFSIZE
        ),

        // Second port: dev control and logs, see DebugProtocol.h
        TUD_CDC_DESCRIPTOR(
            ITF_NUM_CDC_DEBUG,
            STRID_CDC_DEBUG_INTERFACE,
            0x80 | EPNUM_CDC_DEBUG_NOTIF, 8,
            EPNUM_CDC_DEBUG_OUT, 0x80 | EPNUM_CDC_DEBUG_IN,
            64
        ),
    };

    return configurationDescriptor;
}

//--------------------------------------------------------------------
// String Descriptors
//--------------------------------------------------------------------

const u16* tud_descriptor_string_cb(u8 index, u16 langid)
{
    (void)langid;

    if (dsupdate_active())
        return dsupdate_stringDescriptor(index);

    switch (index)
    {
        case STRID_LANGID:
        {
            static const UsbStringDescriptor<2> descriptor(0x0409);  // English
            return (const u16*)&descriptor;
        }
        case STRID_MANUFACTURER:
        {
            return USB_STRING_DESCRIPTOR(u"DSpico");
        }
        case STRID_PRODUCT:
        {
            return USB_STRING_DESCRIPTOR(u"DS Display 256x384");
        }
        case STRID_SERIAL:
        {
            return USB_STRING_DESCRIPTOR(u"DSPICO001");
        }
        case STRID_CDC_INTERFACE:
        {
            return USB_STRING_DESCRIPTOR(u"DS Display Int");
        }
        case STRID_CDC_DEBUG_INTERFACE:
        {
            return USB_STRING_DESCRIPTOR(u"DS Display Debug");
        }
        default:
        {
            return nullptr;
        }
    }
}

//--------------------------------------------------------------------
// CDC Callbacks
//--------------------------------------------------------------------

// Invoked when CDC line state changed (DTR, RTS)
void tud_cdc_line_state_cb(u8 itf, bool dtr, bool rts)
{
    (void)itf;
    (void)rts;
    
    if (dtr)
    {
        // Terminal connected - could signal ready state
    }
}

// Invoked when CDC line coding changed (baud rate, etc)
void tud_cdc_line_coding_cb(u8 itf, cdc_line_coding_t const* p_line_coding)
{
    (void)itf;
    (void)p_line_coding;
    // We ignore baud rate settings - USB is USB speed regardless
}