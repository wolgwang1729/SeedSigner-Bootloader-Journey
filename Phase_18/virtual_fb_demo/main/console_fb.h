#pragma once
#include <stdint.h>

/* Creates an LVGL display (480x800 RGB565) whose flush writes into `fb`,
 * plus a green-on-black monospace transcript screen. Thread-safe print
 * from any task via console_fb_print(). Runs its own LVGL task. */
void console_fb_init(uint16_t *fb);

/* Queue one transcript line (truncated to 64 chars, non-blocking). */
void console_fb_print(const char *line);

/* Clear the transcript. */
void console_fb_clear(void);
