#pragma once

#include <nds/ndstypes.h>

#define DEBUG_CDC_ITF   1

/// @brief Starts the dev port thread. Call after TinyUSB is running.
void debug_init();

/// @brief Wakes the dev port thread. Safe from IRQ context.
void debug_wake();
