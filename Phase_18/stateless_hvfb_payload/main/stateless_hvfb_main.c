/* Stateless HVFB payload entry (app_main).
 *
 * Runs AFTER the SeedSigner secure loader's JMP: PSRAM holds the verified
 * image, the Cache MMU maps IROM/DROM from PSRAM, and the shim
 * (components/stateless_shim) has already replayed early boot (clocks, MMU
 * software contexts, init fns, PSRAM heap, CLIC vectors) into
 * esp_startup_start_app(). From here this is an ordinary IDF app: bring up
 * the virtual display + emulated touch and idle on the console.
 *
 * The payload never touches flash or SD (loader unmounted the card pre-JMP).
 */
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "esp_log.h"
#include "esp_system.h"
#include "esp_chip_info.h"

#include "hvfb_stateless.h"

static const char *TAG = "P18S";

void app_main(void)
{
    esp_chip_info_t chip_info;
    esp_chip_info(&chip_info);
    unsigned major_rev = chip_info.revision / 100;
    unsigned minor_rev = chip_info.revision % 100;
    ESP_LOGI(TAG, "stateless HVFB payload boot (silicon rev v%d.%d, %d core(s))",
             major_rev, minor_rev, chip_info.cores);
    ESP_LOGI(TAG, "minimum free heap: %lu bytes", (unsigned long)esp_get_minimum_free_heap_size());

    if (hvfbs_init() != 0) {
        ESP_LOGE(TAG, "virtual display init failed — halting");
        while (1) {
            vTaskDelay(pdMS_TO_TICKS(1000));
        }
    }

    ESP_LOGI(TAG, "stateless display up: type 'dump' (UART stream) or 'tap x y'");
    /* Console + LVGL + heartbeat tasks own the CPU from here. */
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(60000));
    }
}
