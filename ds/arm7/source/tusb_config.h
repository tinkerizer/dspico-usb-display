#pragma once

#ifdef __cplusplus
extern "C" {
#endif

//--------------------------------------------------------------------+
// Board Specific Configuration
//--------------------------------------------------------------------+

#ifndef BOARD_TUD_RHPORT
#define BOARD_TUD_RHPORT      0
#endif

#ifndef BOARD_TUD_MAX_SPEED
#define BOARD_TUD_MAX_SPEED   OPT_MODE_DEFAULT_SPEED
#endif

//--------------------------------------------------------------------
// COMMON CONFIGURATION
//--------------------------------------------------------------------

#ifndef CFG_TUSB_MCU
#define CFG_TUSB_MCU          OPT_MCU_DSPICO
#endif

#define TUP_DCD_ENDPOINT_MAX    16

#ifndef CFG_TUSB_OS
#define CFG_TUSB_OS           OPT_OS_CUSTOM
#endif

#ifndef CFG_TUSB_DEBUG
#define CFG_TUSB_DEBUG        0
#endif

// Enable Device stack
#define CFG_TUD_ENABLED       1

#define CFG_TUD_MAX_SPEED     BOARD_TUD_MAX_SPEED

#ifndef CFG_TUSB_MEM_SECTION
#define CFG_TUSB_MEM_SECTION
#endif

#ifndef CFG_TUSB_MEM_ALIGN
#define CFG_TUSB_MEM_ALIGN          __attribute__ ((aligned(4)))
#endif

//--------------------------------------------------------------------
// DEVICE CONFIGURATION
//--------------------------------------------------------------------

#ifndef CFG_TUD_ENDPOINT0_SIZE
#define CFG_TUD_ENDPOINT0_SIZE    64
#endif

//------------- CLASS -------------//
#define CFG_TUD_CDC               2
#define CFG_TUD_MSC               1
#define CFG_TUD_HID               0
#define CFG_TUD_MIDI              0
#define CFG_TUD_AUDIO             0
#define CFG_TUD_VENDOR            0

//--------------------------------------------------------------------
// CDC CLASS DRIVER CONFIGURATION
//--------------------------------------------------------------------

// CDC FIFO buffer sizes
// RX buffer needs to be large enough for bulk pixel data, and must be at
// least 2x CFG_TUD_CDC_EP_BUFSIZE so a new OUT transfer can be queued while
// the main loop drains the previous one.
#define CFG_TUD_CDC_RX_BUFSIZE    8192
#define CFG_TUD_CDC_TX_BUFSIZE    1024

// CDC endpoint TRANSFER buffer size (not wMaxPacketSize — that stays 64 in
// the descriptor). The CDC driver posts one OUT transfer of this size at a
// time, and each transfer costs DSpico card-bus round trips. At 64 bytes
// per transfer the card-bus overhead dominates and throughput collapses;
// 4096 lets the DSpico pipeline eight 512-byte hops per transfer.
#define CFG_TUD_CDC_EP_BUFSIZE    4096

// Only used while the SD card is lent to the host. The linker script keeps this
// buffer in main RAM, as IWRAM is nearly full.
#define CFG_TUD_MSC_EP_BUFSIZE    8192

#ifdef __cplusplus
}
#endif