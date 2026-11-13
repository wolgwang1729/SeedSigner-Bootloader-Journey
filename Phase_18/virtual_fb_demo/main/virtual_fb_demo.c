/* Phase 18 virtual framebuffer demo v2: the console REPL on a virtual screen.
 *
 * Target: ESP32-P4-WIFI6-DEV-KIT (headless). Runs from flash like a normal
 * IDF app — it is NOT the stateless loader (loader source of truth:
 * ~/Desktop/seedsigner-esp32-bootloader). Every console line (input echo +
 * responses) is mirrored into an LVGL transcript screen (UNSCII-8,
 * green-on-black) that renders into the 480x800 RGB565 PSRAM framebuffer
 * via a custom flush_cb — the same seam the MicroPython builder's
 * board_init NULL-panel branch will use. Export unchanged: SD dump
 * (fb0.raw/.ppm/fb_info.txt) + UART FB_BEGIN/FB_CHUNK/FB_END stream for
 * Phase_18/tools/fb_viewer.py.
 *
 * Frame format: 480x800, RGB565 little-endian, row-major, top-left origin.
 *   len = 480*800*2 = 768000 bytes.
 *
 * Console commands (type + Enter in the monitor):
 *   help | info | dump | save | clear
 */

#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdarg.h>
#include <stdlib.h>
#include <sys/stat.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_system.h"

#include "esp_vfs_fat.h"
#include "sdmmc_cmd.h"
#include "driver/sdmmc_host.h"
#include "sd_pwr_ctrl_by_on_chip_ldo.h"

#include "console_fb.h"

#define P18_W 480
#define P18_H 800
#define P18_BPP 2
#define P18_LEN ((uint32_t)P18_W * (uint32_t)P18_H * P18_BPP)
#define P18_CHUNK_RAW 192

static const char *TAG = "P18";

/* 480x800 portrait like the ST7701 panel. */
static uint16_t *s_fb;
/* While true the heartbeat stays silent so dump lines can't interleave. */
static volatile bool s_streaming;

/* printf + mirror to the virtual screen. */
static void say(const char *fmt, ...)
{
    char buf[128];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    printf("%s\n", buf);
    console_fb_print(buf);
}

/* ---- CRC32 (IEEE, software, no deps) ---- */
static uint32_t crc32_tab[256];
static bool crc32_ready;

static void crc32_init(void)
{
    if (crc32_ready) {
        return;
    }
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++) {
            c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        }
        crc32_tab[i] = c;
    }
    crc32_ready = true;
}

static uint32_t crc32_of(const uint8_t *p, uint32_t len)
{
    crc32_init();
    uint32_t c = 0xFFFFFFFFu;
    for (uint32_t i = 0; i < len; i++) {
        c = crc32_tab[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    }
    return c ^ 0xFFFFFFFFu;
}

/* ---- base64 (self-contained) ---- */
static const char b64tab[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static int b64_encode(const uint8_t *in, int in_len, char *out)
{
    int o = 0;
    for (int i = 0; i < in_len; i += 3) {
        int n = in_len - i;
        if (n > 3) {
            n = 3;
        }
        uint32_t v = 0;
        for (int k = 0; k < n; k++) {
            v |= (uint32_t)in[i + k] << (8 * (2 - k));
        }
        out[o++] = b64tab[(v >> 18) & 63];
        out[o++] = b64tab[(v >> 12) & 63];
        out[o++] = (n > 1) ? b64tab[(v >> 6) & 63] : '=';
        out[o++] = (n > 2) ? b64tab[v & 63] : '=';
    }
    out[o] = '\0';
    return o;
}

/* ---- SD card (same wiring as the stateless loader: LDO4, 4-bit,
 * CLK=43 CMD=44 D0=39 D1=40 D2=41 D3=42, internal pullups). ---- */
#define MOUNT_POINT "/sdcard"

static bool sd_mount(sdmmc_card_t **out_card)
{
    esp_vfs_fat_mount_config_t mount_config = {
        .format_if_mount_failed = false,
        .max_files = 4,
        .allocation_unit_size = 16 * 1024,
    };
    sdmmc_host_t host = SDMMC_HOST_DEFAULT();
    sd_pwr_ctrl_ldo_config_t ldo_config = { .ldo_chan_id = 4 };
    sd_pwr_ctrl_handle_t pwr = NULL;
    if (sd_pwr_ctrl_new_on_chip_ldo(&ldo_config, &pwr) == ESP_OK) {
        host.pwr_ctrl_handle = pwr;
    } else {
        ESP_LOGW(TAG, "LDO power ctrl failed; trying without it");
    }
    sdmmc_slot_config_t slot = SDMMC_SLOT_CONFIG_DEFAULT();
    slot.width = 4;
    slot.clk = 43;
    slot.cmd = 44;
    slot.d0 = 39;
    slot.d1 = 40;
    slot.d2 = 41;
    slot.d3 = 42;
    slot.flags |= SDMMC_SLOT_FLAG_INTERNAL_PULLUP;
    sdmmc_card_t *card = NULL;
    esp_err_t r = esp_vfs_fat_sdmmc_mount(MOUNT_POINT, &host, &slot, &mount_config, &card);
    if (r != ESP_OK) {
        ESP_LOGW(TAG, "SD mount failed (%s); continuing without SD", esp_err_to_name(r));
        return false;
    }
    ESP_LOGI(TAG, "SD mounted at %s", MOUNT_POINT);
    *out_card = card;
    return true;
}

static void sd_unmount(sdmmc_card_t *card)
{
    (void)card;
    esp_vfs_fat_sdcard_unmount(MOUNT_POINT, NULL);
    ESP_LOGI(TAG, "SD unmounted (TOCTOU hygiene, mirrors loader)");
}

/* Dump fb0.raw + fb0.ppm + fb_info.txt. Non-fatal without a card. */
static void dump_to_sd(void)
{
    sdmmc_card_t *card = NULL;
    if (!sd_mount(&card)) {
        say("[P18] SD_DUMP SKIP (no card)");
        return;
    }
    uint32_t crc = crc32_of((const uint8_t *)s_fb, P18_LEN);

    FILE *f = fopen(MOUNT_POINT "/fb0.raw", "wb");
    if (f) {
        size_t w = fwrite(s_fb, 1, P18_LEN, f);
        fclose(f);
        say("[P18] SD_DUMP raw bytes=%u (wrote %u)", (unsigned)P18_LEN, (unsigned)w);
    } else {
        say("[P18] SD_DUMP raw FAILED");
    }

    f = fopen(MOUNT_POINT "/fb0.ppm", "wb");
    if (f) {
        fprintf(f, "P6\n%d %d\n255\n", P18_W, P18_H);
        for (uint32_t i = 0; i < (uint32_t)P18_W * P18_H; i++) {
            uint16_t px = s_fb[i];
            uint8_t r = (uint8_t)(((px >> 11) & 0x1F) * 255 / 31);
            uint8_t g = (uint8_t)(((px >> 5) & 0x3F) * 255 / 63);
            uint8_t b = (uint8_t)((px & 0x1F) * 255 / 31);
            fputc(r, f);
            fputc(g, f);
            fputc(b, f);
        }
        fclose(f);
        say("[P18] SD_DUMP ppm ok");
    } else {
        say("[P18] SD_DUMP ppm FAILED");
    }

    f = fopen(MOUNT_POINT "/fb_info.txt", "w");
    if (f) {
        fprintf(f, "w=%d h=%d fmt=RGB565LE len=%u crc=%08X console=1\n",
                P18_W, P18_H, (unsigned)P18_LEN, (unsigned)crc);
        fclose(f);
    }
    sd_unmount(card);
}

/* Stream the whole frame over UART in FB_CHUNK lines.
 * Yields often so the WDT stays fed; heartbeat is silent meanwhile. */
static void stream_uart(void)
{
    if (s_streaming) {
        say("[P18] dump already running");
        return;
    }
    s_streaming = true;
    vTaskDelay(pdMS_TO_TICKS(1100)); /* let any in-flight alive line finish */
    /* NOTE: FB_* lines go to printf only, never say(): base64 must stay
     * out of the screen transcript. */
    uint32_t crc = crc32_of((const uint8_t *)s_fb, P18_LEN);
    printf("FB_BEGIN %d %d %u %08X\n", P18_W, P18_H, (unsigned)P18_LEN, (unsigned)crc);
    const uint8_t *p = (const uint8_t *)s_fb;
    uint32_t off = 0;
    uint32_t seq = 0;
    char b64[256 + 1];
    while (off < P18_LEN) {
        uint32_t n = P18_LEN - off;
        if (n > P18_CHUNK_RAW) {
            n = P18_CHUNK_RAW;
        }
        b64_encode(p + off, (int)n, b64);
        printf("FB_CHUNK %u %s\n", (unsigned)seq, b64);
        off += n;
        seq++;
        if ((seq & 15) == 0) {
            vTaskDelay(1);
        }
    }
    printf("FB_END %u\n", (unsigned)seq);
    s_streaming = false;
    say("[P18] UART_STREAM chunks=%u crc=%08X", (unsigned)seq, (unsigned)crc);
}

static void console_task(void *arg)
{
    (void)arg;
    char line[64];
    say("[P18] console ready: help|info|dump|save|clear");
    while (1) {
        if (fgets(line, sizeof(line), stdin) == NULL) {
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }
        line[strcspn(line, "\r\n")] = '\0';
        if (!line[0]) {
            continue;
        }
        char echo[70];
        snprintf(echo, sizeof(echo), "> %s", line);
        console_fb_print(echo);
        if (strncmp(line, "dump", 4) == 0) {
            stream_uart();
        } else if (strncmp(line, "save", 4) == 0) {
            dump_to_sd();
        } else if (strncmp(line, "clear", 5) == 0) {
            console_fb_clear();
            printf("[P18] screen cleared\n");
        } else if (strncmp(line, "info", 4) == 0) {
            uint32_t crc = crc32_of((const uint8_t *)s_fb, P18_LEN);
            say("[P18] FB addr=%p len=%u crc=%08X psram_free=%u",
                (void *)s_fb, (unsigned)P18_LEN, (unsigned)crc,
                (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        } else {
            say("[P18] cmds: help|info|dump|save|clear");
        }
    }
}

void app_main(void)
{
    s_fb = heap_caps_malloc(P18_LEN, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!s_fb) {
        /* Fallback so the demo still runs where PSRAM is missing. */
        s_fb = malloc(P18_LEN);
    }
    if (!s_fb) {
        ESP_LOGE(TAG, "framebuffer alloc failed (%u bytes)", (unsigned)P18_LEN);
        while (1) {
            vTaskDelay(pdMS_TO_TICKS(1000));
        }
    }
    memset(s_fb, 0, P18_LEN);

    console_fb_init(s_fb);

    say("[P18] virtual console boot (degraded: no panel, no camera)");
    say("[P18] frame=%dx%d RGB565LE len=%u", P18_W, P18_H, (unsigned)P18_LEN);
    say("[P18] this screen mirrors the REPL: type help");

    /* Let LVGL render the first frame before the automatic SD dump. */
    vTaskDelay(pdMS_TO_TICKS(500));
    dump_to_sd();

    xTaskCreate(console_task, "p18_console", 4096, NULL, 4, NULL);

    /* Heartbeat: proves no WDT wedge while the FB sits in PSRAM.
     * Silent during UART dumps so chunk lines can't interleave. */
    uint32_t n = 0;
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(5000));
        n++;
        if (s_streaming) {
            continue;
        }
        uint32_t crc = crc32_of((const uint8_t *)s_fb, P18_LEN);
        say("[P18] alive tick=%u crc=%08X free=%u",
            (unsigned)n, (unsigned)crc,
            (unsigned)heap_caps_get_free_size(MALLOC_CAP_DEFAULT));
    }
}
