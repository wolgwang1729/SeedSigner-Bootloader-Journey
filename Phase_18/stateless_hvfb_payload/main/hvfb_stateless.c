/* Stateless virtual display + emulated touch — see hvfb_stateless.h.
 *
 * Merges the silicon-proven halves of Phase 18:
 *   console_fb.c  -> lv_init + esp_timer tick + lv task + transcript queue
 *   headless_virtual_fb.c -> memcpy flush_cb + pointer indev (tap/swipe
 *     synthesis) + base64/CRC32 UART streamer + console command set
 * minus the esp_lvgl_port dependency (lvgl_port_lock/unlock), which the
 * stateless shim payload does not link.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"

#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"

#include "lvgl.h"

#include "hvfb_stateless.h"

#define HVFBS_W 480
#define HVFBS_H 800
#define HVFBS_BPP 2
#define HVFBS_LEN ((uint32_t)HVFBS_W * (uint32_t)HVFBS_H * HVFBS_BPP)
#define HVFBS_CHUNK_RAW 192 /* must match tools/fb_live.py reassembly */
#define HVFBS_DRAW_ROWS 40  /* partial-render band height */

static const char *TAG = "HVFB-S";

static uint16_t *s_fb;
static lv_display_t *s_disp;
static lv_obj_t *s_transcript;
static QueueHandle_t s_q;

static char s_text[8192];
static size_t s_text_len;

/* While true the heartbeat stays silent so dump lines can't interleave. */
static volatile bool s_streaming;

/* ---- emulated touch state (written by console task, read by LVGL task) ---- */
static SemaphoreHandle_t s_touch_mutex;
static volatile int s_tx, s_ty;            /* press point, firmware pixels */
static volatile int64_t s_press_until_us;  /* auto-release deadline */
static volatile int s_sx0, s_sy0, s_sx1, s_sy1;
static volatile int64_t s_swipe_t0_us;
static volatile int s_swipe_phase; /* 0 idle, >0 swipe in progress */

#define TAP_HOLD_US   150000
#define SWIPE_STEP_US  40000
#define SWIPE_STEPS    8

/* ---- last button selection (written in LVGL task, read by console) ---- */
static volatile int s_last_btn = -1;
static const char *const s_btn_names[4] = { "BTN_A", "BTN_B", "BTN_C", "BTN_D" };

/* ---- CRC32 (IEEE, copy of the proven demo implementation) ---- */
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

/* ---- base64 (copy of the proven demo implementation) ---- */
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

/* ---- LVGL flush: draw bufs -> virtual FB ---- */
static void hvfbs_flush(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    int w = area->x2 - area->x1 + 1;
    int h = area->y2 - area->y1 + 1;
    if (area->x1 < 0 || area->y1 < 0 || area->x2 >= HVFBS_W || area->y2 >= HVFBS_H) {
        lv_display_flush_ready(disp);
        return;
    }
    const uint16_t *src = (const uint16_t *)px_map;
    for (int y = 0; y < h; y++) {
        memcpy(&s_fb[(uint32_t)(area->y1 + y) * (uint32_t)HVFBS_W + (uint32_t)area->x1],
               &src[(uint32_t)y * (uint32_t)w],
               (size_t)w * 2);
    }
    lv_display_flush_ready(disp);
}

/* ---- pointer indev: tap pulse + linear swipe synthesis ---- */
static void hvfbs_touch_read(lv_indev_t *indev, lv_indev_data_t *data)
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

/* ---- transcript (LVGL-task context only) ---- */
static void transcript_append(const char *line)
{
    size_t n = strlen(line);
    while (s_text_len + n + 2 > sizeof(s_text)) {
        char *nl = strchr(s_text, '\n');
        if (!nl) {
            s_text_len = 0;
            s_text[0] = '\0';
            break;
        }
        size_t drop = (size_t)(nl - s_text) + 1;
        memmove(s_text, s_text + drop, s_text_len - drop);
        s_text_len -= drop;
    }
    memcpy(s_text + s_text_len, line, n);
    s_text_len += n;
    s_text[s_text_len++] = '\n';
    s_text[s_text_len] = '\0';
    lv_label_set_text(s_transcript, s_text);
}

/* Queue one transcript line from any task (truncated, non-blocking). */
static void transcript_print(const char *line)
{
    if (!s_q) {
        return;
    }
    char buf[65];
    snprintf(buf, sizeof(buf), "%s", line ? line : "");
    xQueueSend(s_q, buf, 0);
}

/* printf + mirror to the virtual screen. */
static void say(const char *fmt, ...)
{
    char buf[96];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    printf("%s\n", buf);
    transcript_print(buf);
}

static void lv_task(void *arg)
{
    (void)arg;
    char line[65];
    while (1) {
        while (xQueueReceive(s_q, line, 0) == pdTRUE) {
            if (line[0] == '\f') {
                s_text_len = 0;
                s_text[0] = '\0';
                lv_label_set_text(s_transcript, "");
            } else {
                transcript_append(line);
            }
        }
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static void tick_cb(void *arg)
{
    (void)arg;
    lv_tick_inc(5);
}

/* ---- button pad ---- */
static void btn_event_cb(lv_event_t *e)
{
    int idx = (int)(intptr_t)lv_event_get_user_data(e);
    s_last_btn = idx;
    say("[HVFB-S] pressed %s (#%d)", s_btn_names[idx], idx);
}

static void build_ui(void)
{
    lv_obj_t *scr = lv_display_get_screen_active(s_disp);
    lv_obj_set_style_bg_color(scr, lv_color_black(), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);

    /* Transcript occupies the upper ~3/4. */
    s_transcript = lv_label_create(scr);
    lv_obj_set_width(s_transcript, HVFBS_W - 8);
    lv_obj_set_pos(s_transcript, 4, 4);
    lv_obj_set_height(s_transcript, 596);
    lv_obj_set_style_text_font(s_transcript, &lv_font_unscii_8, LV_PART_MAIN);
    lv_obj_set_style_text_color(s_transcript, lv_color_hex(0x00ff00), LV_PART_MAIN);
    lv_label_set_long_mode(s_transcript, LV_LABEL_LONG_WRAP);
    lv_label_set_text(s_transcript, "");

    /* 2x2 button pad along the bottom. */
    lv_obj_t *pad = lv_obj_create(scr);
    lv_obj_set_size(pad, HVFBS_W, 196);
    lv_obj_set_pos(pad, 0, HVFBS_H - 196);
    lv_obj_set_style_bg_color(pad, lv_color_hex(0x111111), LV_PART_MAIN);
    lv_obj_set_style_border_width(pad, 0, LV_PART_MAIN);
    lv_obj_set_style_pad_all(pad, 8, LV_PART_MAIN);
    lv_obj_set_layout(pad, LV_LAYOUT_GRID);
    static const int32_t col_dsc[] = { (HVFBS_W - 24) / 2, (HVFBS_W - 24) / 2, LV_GRID_TEMPLATE_LAST };
    static const int32_t row_dsc[] = { 84, 84, LV_GRID_TEMPLATE_LAST };
    lv_obj_set_grid_dsc_array(pad, col_dsc, row_dsc);
    lv_obj_set_style_pad_gap(pad, 8, LV_PART_MAIN);

    for (int i = 0; i < 4; i++) {
        lv_obj_t *btn = lv_btn_create(pad);
        lv_obj_set_grid_cell(btn, LV_GRID_ALIGN_STRETCH, i % 2, 1,
                             LV_GRID_ALIGN_STRETCH, i / 2, 1);
        lv_obj_add_event_cb(btn, btn_event_cb, LV_EVENT_CLICKED,
                            (void *)(intptr_t)i);
        lv_obj_t *lbl = lv_label_create(btn);
        lv_label_set_text(lbl, s_btn_names[i]);
        lv_obj_center(lbl);
    }
}

/* ---- UART streamer (exact fb_live.py protocol) ---- */
static void hvfbs_stream(void)
{
    uint32_t crc = crc_of((const uint8_t *)s_fb, HVFBS_LEN);
    /* NOTE: FB_* lines go to printf only, never say(): base64 must stay
     * out of the screen transcript. */
    printf("FB_BEGIN %d %d %u %08X\n", HVFBS_W, HVFBS_H,
           (unsigned)HVFBS_LEN, (unsigned)crc);
    const uint8_t *p = (const uint8_t *)s_fb;
    uint32_t off = 0, seq = 0;
    char b64[256 + 1];
    while (off < HVFBS_LEN) {
        uint32_t n = HVFBS_LEN - off;
        if (n > HVFBS_CHUNK_RAW) {
            n = HVFBS_CHUNK_RAW;
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

static void hvfbs_result_print(void)
{
    int sel = s_last_btn;
    if (sel >= 0 && sel < 4) {
        printf("[HVFB-S] result: button_selected #%d '%s'\n", sel, s_btn_names[sel]);
    } else {
        printf("[HVFB-S] result: (none yet — tap a button)\n");
    }
}

/* ---- console: dump | tap x y | swipe x0 y0 x1 y1 | info | result ---- */
static void hvfbs_console_task(void *arg)
{
    (void)arg;
    char line[96];
    say("[HVFB-S] console ready: dump|tap|swipe|info|result");
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
            if (s_streaming) {
                say("[HVFB-S] dump already running");
                continue;
            }
            s_streaming = true;
            vTaskDelay(pdMS_TO_TICKS(1100)); /* let in-flight lines finish */
            hvfbs_stream();
            s_streaming = false;
            uint32_t crc = crc_of((const uint8_t *)s_fb, HVFBS_LEN);
            say("[HVFB-S] UART_STREAM chunks=4000 crc=%08X", (unsigned)crc);
        } else if (strncmp(line, "tap", 3) == 0) {
            int x = 0, y = 0;
            if (sscanf(line, "tap %d %d", &x, &y) != 2) {
                say("[HVFB-S] usage: tap x y (0..%d, 0..%d)", HVFBS_W - 1, HVFBS_H - 1);
                continue;
            }
            if (xSemaphoreTake(s_touch_mutex, portMAX_DELAY) == pdTRUE) {
                s_tx = x < 0 ? 0 : (x >= HVFBS_W ? HVFBS_W - 1 : x);
                s_ty = y < 0 ? 0 : (y >= HVFBS_H ? HVFBS_H - 1 : y);
                s_swipe_phase = 0;
                s_press_until_us = esp_timer_get_time() + TAP_HOLD_US;
                xSemaphoreGive(s_touch_mutex);
            }
            say("[HVFB-S] tap %d %d", s_tx, s_ty);
        } else if (strncmp(line, "swipe", 5) == 0) {
            int x0 = 0, y0 = 0, x1 = 0, y1 = 0;
            if (sscanf(line, "swipe %d %d %d %d", &x0, &y0, &x1, &y1) != 4) {
                say("[HVFB-S] usage: swipe x0 y0 x1 y1");
                continue;
            }
            if (xSemaphoreTake(s_touch_mutex, portMAX_DELAY) == pdTRUE) {
                s_sx0 = x0 < 0 ? 0 : (x0 >= HVFBS_W ? HVFBS_W - 1 : x0);
                s_sy0 = y0 < 0 ? 0 : (y0 >= HVFBS_H ? HVFBS_H - 1 : y0);
                s_sx1 = x1 < 0 ? 0 : (x1 >= HVFBS_W ? HVFBS_W - 1 : x1);
                s_sy1 = y1 < 0 ? 0 : (y1 >= HVFBS_H ? HVFBS_H - 1 : y1);
                s_swipe_t0_us = esp_timer_get_time();
                s_swipe_phase = 1;
                xSemaphoreGive(s_touch_mutex);
            }
            say("[HVFB-S] swipe %d %d -> %d %d", s_sx0, s_sy0, s_sx1, s_sy1);
        } else if (strncmp(line, "result", 6) == 0) {
            hvfbs_result_print();
        } else if (strncmp(line, "info", 4) == 0) {
            uint32_t crc = crc_of((const uint8_t *)s_fb, HVFBS_LEN);
            say("[HVFB-S] fb %dx%d len=%u crc=%08X free=%u",
                HVFBS_W, HVFBS_H, (unsigned)HVFBS_LEN, (unsigned)crc,
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        } else {
            say("[HVFB-S] cmds: dump|tap x y|swipe x0 y0 x1 y1|info|result");
        }
    }
}

static void heartbeat_task(void *arg)
{
    (void)arg;
    uint32_t n = 0;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(5000));
        n++;
        if (s_streaming) {
            continue;
        }
        uint32_t crc = crc_of((const uint8_t *)s_fb, HVFBS_LEN);
        say("[HVFB-S] alive tick=%u crc=%08X free=%u",
            (unsigned)n, (unsigned)crc,
            (unsigned)heap_caps_get_free_size(MALLOC_CAP_DEFAULT));
    }
}

uint16_t *hvfbs_get_fb(void) { return s_fb; }

int hvfbs_init(void)
{
    if (s_fb) {
        return -1; /* already initialised */
    }

    s_fb = heap_caps_malloc(HVFBS_LEN, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_fb) {
        s_fb = malloc(HVFBS_LEN); /* fallback so bring-up still runs */
    }
    if (!s_fb) {
        ESP_LOGE(TAG, "framebuffer alloc failed (%u bytes)", (unsigned)HVFBS_LEN);
        return -1;
    }
    memset(s_fb, 0, HVFBS_LEN);
    memset(s_text, 0, sizeof(s_text));
    s_text_len = 0;

    s_touch_mutex = xSemaphoreCreateMutex();
    if (!s_touch_mutex) {
        ESP_LOGE(TAG, "touch mutex alloc failed");
        return -1;
    }

    /* LVGL core: same bring-up as the proven virtual_fb_demo (no
     * esp_lvgl_port — the shim payload does not link it). */
    lv_init();

    const esp_timer_create_args_t tick_args = {
        .callback = tick_cb,
        .name = "hvfbs_lvgl_tick",
    };
    esp_timer_handle_t tick = NULL;
    if (esp_timer_create(&tick_args, &tick) != ESP_OK ||
        esp_timer_start_periodic(tick, 5000) != ESP_OK) {
        ESP_LOGE(TAG, "lvgl tick timer failed");
        return -1;
    }

    s_disp = lv_display_create(HVFBS_W, HVFBS_H);
    lv_display_set_color_format(s_disp, LV_COLOR_FORMAT_RGB565);

    size_t draw_sz = (size_t)HVFBS_W * HVFBS_DRAW_ROWS * 2u;
    void *buf1 = heap_caps_malloc(draw_sz, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    void *buf2 = heap_caps_malloc(draw_sz, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!buf1 || !buf2) {
        ESP_LOGE(TAG, "draw buf alloc failed");
        return -1;
    }
    lv_display_set_buffers(s_disp, buf1, buf2, draw_sz, LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(s_disp, hvfbs_flush);

    lv_indev_t *indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, hvfbs_touch_read);
    lv_indev_set_display(indev, s_disp);

    build_ui();

    s_q = xQueueCreate(32, 65);
    if (!s_q) {
        ESP_LOGE(TAG, "transcript queue alloc failed");
        return -1;
    }
    xTaskCreate(lv_task, "hvfbs_lvgl", 8192, NULL, 4, NULL);
    xTaskCreate(hvfbs_console_task, "hvfbs_console", 4096, NULL, 4, NULL);
    xTaskCreate(heartbeat_task, "hvfbs_alive", 3072, NULL, 3, NULL);

    ESP_LOGI(TAG, "stateless virtual FB %dx%d (%u bytes, PSRAM), touch indev ready",
             HVFBS_W, HVFBS_H, (unsigned)HVFBS_LEN);
    return 0;
}
