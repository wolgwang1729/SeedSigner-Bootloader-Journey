/* Phase 18 console mirror: LVGL transcript screen -> virtual framebuffer.
 *
 * Same seam the MicroPython builder will use (board_init.c NULL-panel
 * branch): lv_display_create + PSRAM draw buffers + custom flush_cb that
 * memcpy's into the exported 480x800 RGB565 framebuffer. No DSI, no panel.
 */
#include <string.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

#include "esp_heap_caps.h"
#include "esp_timer.h"

#include "lvgl.h"

#include "console_fb.h"

#define UI_W 480
#define UI_H 800
#define UI_TEXT_MAX 8192

static uint16_t *s_fb;
static lv_display_t *s_disp;
static lv_obj_t *s_label;
static QueueHandle_t s_q;

static char s_text[UI_TEXT_MAX];
static size_t s_text_len;

static void ui_flush(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    int w = area->x2 - area->x1 + 1;
    int h = area->y2 - area->y1 + 1;
    if (area->x1 < 0 || area->y1 < 0 || area->x2 >= UI_W || area->y2 >= UI_H) {
        lv_display_flush_ready(disp);
        return;
    }
    const uint16_t *src = (const uint16_t *)px_map;
    for (int y = 0; y < h; y++) {
        memcpy(&s_fb[(uint32_t)(area->y1 + y) * UI_W + (uint32_t)area->x1],
               &src[(uint32_t)y * (uint32_t)w],
               (size_t)w * 2);
    }
    lv_display_flush_ready(disp);
}

static void transcript_append(const char *line)
{
    size_t n = strlen(line);
    /* Room for line + '\n' + NUL; drop oldest lines first. */
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
    lv_label_set_text(s_label, s_text);
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
                lv_label_set_text(s_label, "");
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

void console_fb_init(uint16_t *fb)
{
    s_fb = fb;
    memset(s_text, 0, sizeof(s_text));
    s_text_len = 0;

    lv_init();

    const esp_timer_create_args_t tick_args = {
        .callback = tick_cb,
        .name = "p18_lvgl_tick",
    };
    esp_timer_handle_t tick = NULL;
    esp_timer_create(&tick_args, &tick);
    esp_timer_start_periodic(tick, 5000);

    s_disp = lv_display_create(UI_W, UI_H);
    lv_display_set_color_format(s_disp, LV_COLOR_FORMAT_RGB565);

    size_t buf_sz = (size_t)UI_W * UI_H * 2;
    void *buf1 = heap_caps_malloc(buf_sz, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    void *buf2 = heap_caps_malloc(buf_sz, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    configASSERT(buf1 && buf2);
    lv_display_set_buffers(s_disp, buf1, buf2, buf_sz, LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(s_disp, ui_flush);

    lv_obj_t *scr = lv_display_get_screen_active(s_disp);
    lv_obj_set_style_bg_color(scr, lv_color_black(), LV_PART_MAIN);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, LV_PART_MAIN);

    s_label = lv_label_create(scr);
    lv_obj_set_width(s_label, UI_W - 8);
    lv_obj_set_pos(s_label, 4, 4);
    lv_obj_set_style_text_font(s_label, &lv_font_unscii_8, LV_PART_MAIN);
    lv_obj_set_style_text_color(s_label, lv_color_hex(0x00ff00), LV_PART_MAIN);
    lv_label_set_long_mode(s_label, LV_LABEL_LONG_WRAP);
    lv_label_set_text(s_label, "");

    s_q = xQueueCreate(32, 65);
    configASSERT(s_q);
    xTaskCreate(lv_task, "p18_lvgl", 8192, NULL, 4, NULL);
}

void console_fb_print(const char *line)
{
    if (!s_q) {
        return;
    }
    char buf[65];
    snprintf(buf, sizeof(buf), "%s", line ? line : "");
    xQueueSend(s_q, buf, 0);
}

void console_fb_clear(void)
{
    /* Runs in LVGL task context via an empty-line sentinel? No: simplest is
     * to queue a form-feed marker the lv task interprets. */
    const char ff[65] = "\f";
    if (s_q) {
        xQueueSend(s_q, ff, 0);
    }
}
