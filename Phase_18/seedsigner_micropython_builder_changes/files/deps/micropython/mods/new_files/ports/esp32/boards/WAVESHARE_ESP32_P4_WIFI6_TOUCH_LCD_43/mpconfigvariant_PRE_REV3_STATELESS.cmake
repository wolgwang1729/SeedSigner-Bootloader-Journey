# Stateless PSRAM-execution variant of PRE_REV3 (older v0.x/v1.x silicon).
#
#   BOARD_VARIANT=PRE_REV3_STATELESS make docker-build-all
#
# Builds the same firmware as PRE_REV3 plus the stateless-loader handoff
# prerequisites (sdkconfig.stateless, appended AFTER sdkconfig.board so it
# wins): single-core, PMP-split off, 115200 default-UART console (the loader's
# console — no mid-boot baud switch), loader-matching partition offset.
# Output: build/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43-PRE_REV3_STATELESS/micropython.bin
# (an app image: sign it into a Specter bundle, do NOT flash it directly).
list(APPEND SDKCONFIG_DEFAULTS
    boards/sdkconfig.p4_pre_rev3
    boards/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43/sdkconfig.stateless
)
