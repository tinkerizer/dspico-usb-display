#pragma once

#include <nds/ndstypes.h>

void debug_init();

/// @brief Sends printf-style text to the host over the dev port. Dropped if the ring is full.
void debug_log(const char* format, ...) __attribute__((format(printf, 1, 2)));

/// @brief Copies both screens to DEBUG_CAPTURE_BASE and tells the ARM7.
void debug_capture(const void* topScreen, const void* bottomScreen);

/// @brief Starts the reboot if the ARM7 requested one. Does not return in that case.
void debug_checkReboot();
