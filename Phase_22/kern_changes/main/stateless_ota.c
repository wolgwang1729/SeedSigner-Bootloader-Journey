// Phase 22 stateless compatibility shim.
//
// A stateless payload executes from PSRAM, not from its flash app partition.
// esp_ota_get_running_partition() locates the running image by translating the
// address of its own code through spi_flash_cache2phys(); that translation does
// not describe a PSRAM XIP address and the function eventually aborts. IDF's
// esp_partition_main_flash_region_safe() and Kern's fw_update_boot_confirm()
// both call it, so return the payload's metadata app partition instead.

#include "sdkconfig.h"

#if CONFIG_KERN_STATELESS

#include <esp_partition.h>

static const esp_partition_t s_stateless_fallback = {
    .flash_chip = NULL,
    .type = ESP_PARTITION_TYPE_APP,
    .subtype = ESP_PARTITION_SUBTYPE_APP_FACTORY,
    .address = 0x30000,
    .size = 0x200000,
    .erase_size = 0x1000,
    .label = "factory",
    .encrypted = false,
    .readonly = false,
};

const esp_partition_t *__wrap_esp_ota_get_running_partition(void) {
  const esp_partition_t *part = esp_partition_find_first(
      ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_ANY, NULL);
  if (part != NULL) {
    return part;
  }
  return &s_stateless_fallback;
}

#endif
