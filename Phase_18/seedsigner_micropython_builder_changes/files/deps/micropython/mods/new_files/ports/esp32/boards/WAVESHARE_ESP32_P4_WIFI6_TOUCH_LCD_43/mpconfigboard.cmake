set(IDF_TARGET esp32p4)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.p4
    boards/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43/sdkconfig.board
)

# Insert board hardware sdkconfig from esp-board-common before sdkconfig.board,
# so MicroPython-specific settings in sdkconfig.board take precedence.
if(DEFINED BOARD_CONFIG_DIR AND EXISTS "${BOARD_CONFIG_DIR}/sdkconfig.defaults")
    list(INSERT SDKCONFIG_DEFAULTS 2 "${BOARD_CONFIG_DIR}/sdkconfig.defaults")
endif()

# Freeze the SeedSigner app's required stdlib modules (logging + hmac, from
# micropython-lib) into the firmware so they need not be vendored to /lib.
set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)

# Stateless-loader entry: the shim replays early boot (clocks, MMU contexts,
# init fns, PSRAM heap, CLIC vectors) after the loader's PSRAM-MMU JMP, then
# hands off to esp_startup_start_app. GATED to the PRE_REV3_STATELESS variant:
# the --wrap redirections (call_start_cpu0, heap caps, OTA stubs, ...) must
# NOT leak into flash-execution firmware builds of this board.
if(MICROPY_BOARD_VARIANT STREQUAL "PRE_REV3_STATELESS")
    list(APPEND MICROPY_EXTRA_COMPONENT_DIRS "${MICROPY_BOARD_DIR}/stateless_shim")
endif()
