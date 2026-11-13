/*
 * hello_sram — Phase 20 R5a test payload (C-only, signed bundle).
 *
 * A pure INTERNAL-SRAM payload: built WITHOUT SPIRAM XIP, so the image has
 * zero 0x48xxxxxx segments and the loader plans zero MMU mappings (direct
 * SRAM copies + teardown + jump only). Proves the production loader boots
 * the no-MMU fallback path with no code changes, and gives R5c something
 * MMU-free to attempt.
 *
 * UART commands (newline-terminated): ping, info.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_heap_caps.h"

void app_main(void)
{
    printf("[sram] HELLO_SRAM — pure internal-SRAM payload alive\n");
    printf("[sram] heap internal=%u (no SPIRAM heap in R5a build)\n",
           (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
    fflush(stdout);

    char line[64];
    printf("> ");
    fflush(stdout);
    while (1) {
        if (!fgets(line, sizeof(line), stdin)) {
            vTaskDelay(100 / portTICK_PERIOD_MS);
            continue;
        }
        line[strcspn(line, "\r\n")] = '\0';
        if (strcmp(line, "ping") == 0) {
            printf("PONG\n");
            fflush(stdout);
        } else if (strcmp(line, "info") == 0) {
            printf("SRAM_INFO heap_internal=%u tick=%lu\n",
                   (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                   (unsigned long)xTaskGetTickCount());
            fflush(stdout);
        } else if (line[0] != '\0') {
            printf("UNKNOWN '%s'\n", line);
            fflush(stdout);
        }
        printf("> ");
        fflush(stdout);
    }
}
