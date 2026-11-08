#pragma once

#ifdef __cplusplus
extern "C" {
#endif

// String descriptor indices
enum
{
    STRID_LANGID = 0,
    STRID_MANUFACTURER,
    STRID_PRODUCT,
    STRID_SERIAL,
    STRID_CDC_INTERFACE,
    STRID_CDC_DEBUG_INTERFACE,
};

// Interface numbers
enum
{
    ITF_NUM_CDC = 0,
    ITF_NUM_CDC_DATA,
    ITF_NUM_CDC_DEBUG,
    ITF_NUM_CDC_DEBUG_DATA,
    ITF_NUM_TOTAL
};

// Endpoint numbers
enum
{
    EPNUM_CDC_NOTIF = 1,
    EPNUM_CDC_OUT   = 2,
    EPNUM_CDC_IN    = 2,
    EPNUM_CDC_DEBUG_NOTIF = 3,
    EPNUM_CDC_DEBUG_OUT   = 4,
    EPNUM_CDC_DEBUG_IN    = 4,
};

#define USB_VID     0x1209      // pid.codes VID for open projects
#define USB_PID     0xDD01

#ifdef __cplusplus
}
#endif