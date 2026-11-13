/* Stateless virtual display + emulated touch for the stateless payload.
 *
 * Self-contained LVGL unit adapted from Phase_18/board_common_virtual_fb/
 * (silicon-proven in flash execution) to the stateless shim's
 * no-board_init environment:
 *   - NO esp_lvgl_port dependency (the shim payload does not link it).
 *     LVGL runs on lv_init() + an esp_timer 5 ms tick + a private lv task
 *     calling lv_timer_handler() — the exact pattern proven by
 *     Phase_18/virtual_fb_demo/main/console_fb.c.
 *   - Portrait 480x800 RGB565 framebuffer in PSRAM (same frozen geometry /
 *     UART protocol as the demo, so Phase_18/tools/fb_live.py works as-is).
 *   - UI: green-on-black UNSCII-8 transcript (mirrors console traffic) +
 *     a 2x2 button pad (A/B/C/D). `tap x y` presses buttons; `result`
 *     reports the last selection (durable proof — press flash is ~150 ms).
 *
 * Console protocol (device side, 115200 baud):
 *   dump                  -> FB_BEGIN w h len crc32hex, 4000x FB_CHUNK, FB_END
 *   tap <x> <y>           -> 150 ms press+release pulse at (x,y), clamped
 *   swipe <x0> <y0> <x1> <y1> -> 8-step linear press/move/release (~320 ms)
 *   info                  -> [HVFB-S] fb WxH len= crc= free=
 *   result                -> last button selection (or "(none yet)")
 *
 * Reversible by construction: RAM + UART only. No eFuse, no secure-boot
 * provisioning, no flash writes — the payload never touches flash or SD
 * (the loader already unmounted the card before the JMP).
 */
#pragma once

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Creates the virtual display + touch indev + console task. Returns 0 on
 * success. Call once from app_main (LVGL task + console task are spawned).
 * Safe to call only once; a second call is a no-op returning -1. */
int hvfbs_init(void);

/* Framebuffer for inspection (RGB565LE, row-major, top-left, 480x800). */
uint16_t *hvfbs_get_fb(void);

#ifdef __cplusplus
}
#endif
