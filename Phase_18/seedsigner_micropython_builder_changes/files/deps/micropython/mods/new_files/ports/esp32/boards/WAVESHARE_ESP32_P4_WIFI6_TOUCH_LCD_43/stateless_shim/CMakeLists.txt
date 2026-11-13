idf_component_register(SRCS "stateless_shim.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_hw_support soc hal esp_rom heap esp_common esp_partition)

# Force the linker to pull in our custom entry point, the native function, and __wrap_ symbols
target_link_options(${COMPONENT_LIB} INTERFACE
    "-u __real_call_start_cpu0"
    "-u __wrap_call_start_cpu0"
    "-Wl,-e,my_entry_point"
    "-Wl,--wrap=call_start_cpu0"
    "-Wl,--wrap=cache_hal_init"
    "-Wl,--wrap=spi_flash_init_chip_state"
    "-Wl,--wrap=mspi_timing_flash_tuning"
    "-Wl,--wrap=esp_psram_chip_init"
    "-Wl,--wrap=bootloader_flash_update_id"
    "-Wl,--wrap=image_process"
    "-Wl,--wrap=esp_mspi_pin_init"
    "-Wl,--wrap=esp_mspi_pin_reserve"
    "-Wl,--wrap=esp_rom_output_tx_wait_idle"
    "-Wl,--wrap=esp_rom_uart_set_clock_baudrate"
    "-Wl,--wrap=uart_stdout_init"
    "-Wl,--wrap=esp_rtc_init"
    "-Wl,--wrap=heap_caps_calloc"
    # No OTA / running-partition under stateless: the image runs from PSRAM,
    # so spi_flash_cache2phys can never map it into a flash partition and the
    # stock esp_ota_get_running_partition() aborts ("Partition table is
    # invalid or corrupt"). Report "no such partition" instead; MP's Partition
    # binding converts that to a Python OSError (see esp32_partition.c).
    "-Wl,--wrap=esp_ota_get_running_partition"
    "-Wl,--wrap=esp_ota_mark_app_valid_cancel_rollback"
)
