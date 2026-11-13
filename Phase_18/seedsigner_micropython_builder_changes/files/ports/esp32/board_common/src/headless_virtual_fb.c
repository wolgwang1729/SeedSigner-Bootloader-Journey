/* Headless virtual framebuffer + emulated touch (HEADLESS_VIRTUAL_FB).
 *
 * Logic mirrors SoB Phase_18/virtual_fb_demo/main/{virtual_fb_demo,console_fb}.c
 * (P4-silicon-proven) adapted to the board_common LVGL-port environment:
 * lv_display_create + PSRAM draw bufs + memcpy flush, UART base64 streamer
 * with CRC32, and a pointer indev driven by `tap`/`swipe` console lines.
 *
 * RAM + UART only. No eFuse, no secure-boot, no OTP, no partition changes.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"

#include "board_config.h"

#include "lvgl.h"
#include "esp_lvgl_port.h"

#include "headless_virtual_fb.h"

/* Board geometry comes from the active board_config.h at the hook site. */
#ifndef BOARD_LCD_H_RES
#define BOARD_LCD_H_RES 480
#endif
#ifndef BOARD_LCD_V_RES
#define BOARD_LCD_V_RES 800
#endif

#define HVFB_CHUNK_RAW 192 /* must match tools/fb_live.py reassembly */

static const char *TAG = "HVFB";

static uint16_t *s_fb;
static int s_w, s_h;
static uint32_t s_len;
static lv_display_t *s_disp;
static lv_indev_t *s_indev;

/* ---- emulated touch state (written by console task, read by LVGL task) ---- */
static SemaphoreHandle_t s_touch_mutex;
static volatile int s_tx, s_ty;            /* press point, firmware pixels */
static volatile int64_t s_press_until_us;  /* auto-release deadline */
static volatile bool s_swipe_active;
static volatile int s_sx0, s_sy0, s_sx1, s_sy1;
static volatile int64_t s_swipe_t0_us;
static volatile int s_swipe_phase; /* 0 idle, 1 press, 2 move, 3 release-pending */

#define TAP_HOLD_US   150000
#define SWIPE_STEP_US  40000
#define SWIPE_STEPS    8

/* ---- CRC32 (IEEE, copy of the proven virtual_fb_demo implementation) ---- */
static uint32_t s_crc_tab[256];
static bool s_crc_ready;

static void crc_init(void)
{
    if (s_crc_ready) {
        return;
    }
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++) {
            c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        }
        s_crc_tab[i] = c;
    }
    s_crc_ready = true;
}

static uint32_t crc_of(const uint8_t *p, uint32_t len)
{
    crc_init();
    uint32_t c = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < len; i++) {
        c = s_crc_tab[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    }
    return c ^ 0xFFFFFFFFu;
}

/* ---- base64 (copy of the proven virtual_fb_demo implementation) ---- */
static const char s_b64[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static int b64_encode(const uint8_t *in, int n_in, char *out)
{
    int o = 0;
    for (int i = 0; i < n_in; i += 3) {
        int n = n_in - i;
        if (n > 3) {
            n = 3;
        }
        uint32_t v = 0;
        for (int k = 0; k < n; k++) {
            v |= (uint32_t)in[i + k] << (8 * (2 - k));
        }
        out[o++] = s_b64[(v >> 18) & 63];
        out[o++] = s_b64[(v >> 12) & 63];
        out[o++] = (n > 1) ? s_b64[(v >> 6) & 63] : '=';
        out[o++] = (n > 2) ? s_b64[v & 63] : '=';
    }
    out[o] = '\0';
    return o;
}

/* ---- LVGL flush: draw bufs -> virtual FB (same seam as console_fb.c) ---- */
static void hvfb_flush(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    int w = area->x2 - area->x1 + 1;
    int h = area->y2 - area->y1 + 1;
    if (area->x1 < 0 || area->y1 < 0 || area->x2 >= s_w || area->y2 >= s_h) {
        lv_display_flush_ready(disp);
        return;
    }
    const uint16_t *src = (const uint16_t *)px_map;
    for (int y = 0; y < h; y++) {
        memcpy(&s_fb[(uint32_t)(area->y1 + y) * (uint32_t)s_w + (uint32_t)area->x1],
               &src[(uint32_t)y * (uint32_t)w],
               (size_t)w * 2);
    }
    lv_display_flush_ready(disp);
}

/* ---- pointer indev: tap pulse + linear swipe synthesis ---- */
static void hvfb_touch_read(lv_indev_t *indev, lv_indev_data_t *data)
{
    (void)indev;
    int64_t now = esp_timer_get_time();
    data->state = LV_INDEV_STATE_RELEASED;
    if (xSemaphoreTake(s_touch_mutex, 0) != pdTRUE) {
        return;
    }
    if (s_swipe_phase > 0) {
        int64_t dt = now - s_swipe_t0_us;
        int step = (int)(dt / SWIPE_STEP_US);
        if (step >= SWIPE_STEPS) {
            s_swipe_phase = 0; /* finished: released */
        } else if (step <= 0) {
            data->point.x = s_sx0;
            data->point.y = s_sy0;
            data->state = LV_INDEV_STATE_PRESSED;
        } else {
            data->point.x = s_sx0 + (s_sx1 - s_sx0) * step / SWIPE_STEPS;
            data->point.y = s_sy0 + (s_sy1 - s_sy0) * step / SWIPE_STEPS;
            data->state = LV_INDEV_STATE_PRESSED;
        }
    } else if (now < s_press_until_us) {
        data->point.x = s_tx;
        data->point.y = s_ty;
        data->state = LV_INDEV_STATE_PRESSED;
    }
    xSemaphoreGive(s_touch_mutex);
}

/* ---- UART streamer (exact fb_live.py protocol) ---- */
static void hvfb_stream(void)
{
    uint32_t crc = crc_of((const uint8_t *)s_fb, s_len);
    printf("FB_BEGIN %d %d %u %08X\n", s_w, s_h, (unsigned)s_len, (unsigned)crc);
    const uint8_t *p = (const uint8_t *)s_fb;
    uint32_t off = 0, seq = 0;
    char b64[256 + 1];
    while (off < s_len) {
        uint32_t n = s_len - off;
        if (n > HVFB_CHUNK_RAW) {
            n = HVFB_CHUNK_RAW;
        }
        b64_encode(p + off, (int)n, b64);
        printf("FB_CHUNK %u %s\n", (unsigned)seq, b64);
        off += n;
        seq++;
        if ((seq & 15) == 0) {
            vTaskDelay(1); /* keep the WDT fed over the ~95 s stream */
        }
    }
    printf("FB_END %u\n", (unsigned)seq);
}

/* ---- console: dump | tap x y | swipe x0 y0 x1 y1 | info ---- */
static void hvfb_console_task(void *arg)
{
    (void)arg;
    char line[96];
    printf("[HVFB] console ready: dump|tap|swipe|info|result\n");
    while (1) {
        if (fgets(line, sizeof(line), stdin) == NULL) {
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }
        line[strcspn(line, "\r\n")] = '\0';
        if (!line[0]) {
            continue;
        }
        if (strncmp(line, "dump", 4) == 0) {
            hvfb_stream();
        } else if (strncmp(line, "tap", 3) == 0) {
            int x = 0, y = 0;
            if (sscanf(line, "tap %d %d", &x, &y) != 2) {
                printf("[HVFB] usage: tap x y (0..%d, 0..%d)\n", s_w - 1, s_h - 1);
                continue;
            }
            if (xSemaphoreTake(s_touch_mutex, portMAX_DELAY) == pdTRUE) {
                s_tx = x < 0 ? 0 : (x >= s_w ? s_w - 1 : x);
                s_ty = y < 0 ? 0 : (y >= s_h ? s_h - 1 : y);
                s_swipe_phase = 0;
                s_press_until_us = esp_timer_get_time() + TAP_HOLD_US;
                xSemaphoreGive(s_touch_mutex);
            }
            printf("[HVFB] tap %d %d\n", s_tx, s_ty);
        } else if (strncmp(line, "swipe", 5) == 0) {
            int x0 = 0, y0 = 0, x1 = 0, y1 = 0;
            if (sscanf(line, "swipe %d %d %d %d", &x0, &y0, &x1, &y1) != 4) {
                printf("[HVFB] usage: swipe x0 y0 x1 y1\n");
                continue;
            }
            if (xSemaphoreTake(s_touch_mutex, portMAX_DELAY) == pdTRUE) {
                s_sx0 = x0 < 0 ? 0 : (x0 >= s_w ? s_w - 1 : x0);
                s_sy0 = y0 < 0 ? 0 : (y0 >= s_h ? s_h - 1 : y0);
                s_sx1 = x1 < 0 ? 0 : (x1 >= s_w ? s_w - 1 : x1);
                s_sy1 = y1 < 0 ? 0 : (y1 >= s_h ? s_h - 1 : y1);
                s_swipe_t0_us = esp_timer_get_time();
                s_swipe_phase = 1;
                xSemaphoreGive(s_touch_mutex);
            }
            printf("[HVFB] swipe %d %d -> %d %d\n", s_sx0, s_sy0, s_sx1, s_sy1);
        } else if (strncmp(line, "result", 6) == 0) {
            hvfb_result_print();
        } else if (strncmp(line, "info", 4) == 0) {
            uint32_t crc = crc_of((const uint8_t *)s_fb, s_len);
            printf("[HVFB] fb %dx%d len=%u crc=%08X free=%u\n",
                   s_w, s_h, (unsigned)s_len, (unsigned)crc,
                   (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        } else if (strncmp(line, "heap", 4) == 0) {
            /* Live heap introspection (Phase 18 stateless bring-up): per-caps
             * free + largest block, plus a full integrity walk. `largest`
             * near `free` with integrity OK means one clean region; tiny
             * `largest` against huge `free` means caps mismatch or a severed
             * free list. */
            printf("[HVFB] heap SPIRAM : free=%u largest=%u\n",
                   (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
                   (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
            printf("[HVFB] heap DEFAULT: free=%u largest=%u\n",
                   (unsigned)heap_caps_get_free_size(MALLOC_CAP_DEFAULT),
                   (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_DEFAULT));
            printf("[HVFB] heap INTERN : free=%u largest=%u\n",
                   (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                   (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
            printf("[HVFB] heap integrity: %s\n",
                   heap_caps_check_integrity_all(true) ? "OK" : "CORRUPT");
        } else {
            printf("[HVFB] cmds: dump|tap x y|swipe x0 y0 x1 y1|info|result|heap\n");
        }
    }
}

uint16_t *hvfb_get_fb(void) { return s_fb; }
int hvfb_get_hres(void) { return s_w; }
int hvfb_get_vres(void) { return s_h; }

/* App-provided selection readout for the `result` console command. Weak
 * default so the touch_test build (no screens) still links. */
__attribute__((weak)) void hvfb_result_print(void)
{
    printf("[HVFB] result: (no provider — app defines hvfb_result_print)\n");
}

int hvfb_init(lv_display_t **disp_out, lv_indev_t **touch_out)
{
    return hvfb_init_ex(disp_out, touch_out, 0);
}

int hvfb_init_ex(lv_display_t **disp_out, lv_indev_t **touch_out, int landscape)
{
    if (s_fb) {
        return -1; /* already initialised */
    }
    if (landscape) {
        /* Landscape LVGL display (e.g. SeedSigner 800x480 on the 4.3" panel):
         * the virtual FB matches LVGL pixel-for-pixel, no rotation needed. */
        s_w = BOARD_LCD_V_RES;
        s_h = BOARD_LCD_H_RES;
    } else {
        s_w = BOARD_LCD_H_RES;
        s_h = BOARD_LCD_V_RES;
    }
    s_len = (uint32_t)s_w * (uint32_t)s_h * 2u;

    s_fb = heap_caps_malloc(s_len, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_fb) {
        ESP_LOGE(TAG, "virtual FB alloc failed (%u bytes)", (unsigned)s_len);
        return -1;
    }
    memset(s_fb, 0, s_len);
    s_touch_mutex = xSemaphoreCreateMutex();
    if (!s_touch_mutex) {
        heap_caps_free(s_fb);
        s_fb = NULL;
        return -1;
    }

    size_t draw_sz = (size_t)s_w * 50u * 2u; /* same band size as DSI portrait */
    void *buf1 = heap_caps_malloc(draw_sz, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    void *buf2 = heap_caps_malloc(draw_sz, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!buf1 || !buf2) {
        ESP_LOGE(TAG, "draw buf alloc failed");
        heap_caps_free(s_fb);
        s_fb = NULL;
        return -1;
    }

    /* Caller (lvgl_port_setup) holds no lock here; take it like other branches. */
    lvgl_port_lock(0);
    lv_display_t *disp = lv_display_create(s_w, s_h);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(disp, buf1, buf2, draw_sz, LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(disp, hvfb_flush);
    s_disp = disp;
    if (disp_out) {
        *disp_out = disp;
    }

    s_indev = lv_indev_create();
    lv_indev_set_type(s_indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(s_indev, hvfb_touch_read); /* LVGL 9.x: 2-arg form */
    lv_indev_set_display(s_indev, disp);
    if (touch_out) {
        *touch_out = s_indev;
    }
    lvgl_port_unlock();

    xTaskCreate(hvfb_console_task, "hvfb_console", 4096, NULL, 4, NULL);
    ESP_LOGI(TAG, "headless virtual FB %dx%d (%u bytes, PSRAM), touch indev ready",
             s_w, s_h, (unsigned)s_len);
    return 0;
}
