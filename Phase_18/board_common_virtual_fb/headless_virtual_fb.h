/* Headless virtual framebuffer + emulated touch for esp-board-common.
 *
 * PROVEN on P4 DEV-KIT silicon (Oct 14, 2026) via the _local_ws build copy;
 * see README.md for the hook point. The stateless-shim adaptation of this
 * unit lives in Phase_18/stateless_hvfb_payload/main/hvfb_stateless.c
 * (no esp_lvgl_port dependency).
 *
 * What it does (mirrors Phase_18/virtual_fb_demo, proven on P4 silicon):
 *   - creates an LVGL display (BOARD_LCD_H_RES x BOARD_LCD_V_RES, RGB565)
 *     with PSRAM draw buffers and a memcpy flush_cb into s_fb;
 *   - streams s_fb over the console UART with the exact FB_BEGIN / FB_CHUNK
 *     / FB_END protocol that Phase_18/tools/fb_live.py already speaks;
 *   - creates a pointer-type lv_indev fed by console lines `tap x y` and
 *     `swipe x0 y0 x1 y1` (firmware pixels, GT911 coordinate space).
 *
 * Reversible by construction: pure RAM + UART. No eFuse, no secure-boot,
 * no OTP, no flash-partition changes. Delete the files and the 5-line hook
 * to return to stock behaviour.
 */
#pragma once

#include "lvgl.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Creates the virtual display + touch indev. Returns 0 on success.
 * Safe to call only when the real panel is absent (panel_handle == NULL);
 * otherwise it is a no-op returning -1. */
int hvfb_init(lv_display_t **disp_out, lv_indev_t **touch_out);

/* Landscape variant: virtual FB is V_RES x H_RES (e.g. 800x480 for the
 * SeedSigner 4.3" landscape UI). Portrait (hvfb_init) is H_RES x V_RES. */
int hvfb_init_ex(lv_display_t **disp_out, lv_indev_t **touch_out, int landscape);

/* App-provided selection readout for the `result` console command (weak
 * default prints a placeholder; screens apps override to print last pick). */
void hvfb_result_print(void);

/* Framebuffer for host-side inspection (RGB565LE, row-major, top-left). */
uint16_t *hvfb_get_fb(void);
int hvfb_get_hres(void);
int hvfb_get_vres(void);

#ifdef __cplusplus
}
#endif
