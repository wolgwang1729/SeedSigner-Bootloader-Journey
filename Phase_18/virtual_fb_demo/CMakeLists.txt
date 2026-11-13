# Virtual framebuffer demo (Phase 18, degraded mode)
#
# Standalone ESP-IDF app for the ESP32-P4-WIFI6-DEV-KIT you already own.
# No display or camera hardware required.
#
# What it proves:
#   - a 480x800 RGB565 framebuffer lives in PSRAM and is drawable,
#   - the frame can be exported to SD card (fb0.raw / fb0.ppm / fb_info.txt)
#     and streamed over UART (FB_BEGIN/FB_CHUNK/FB_END) for the desktop viewer,
#   - the same framebuffer is the exact hook point for the LVGL virtual flush
#     in the MicroPython builder's board_init NULL-panel branch.
#
# What it does NOT prove (must stay labelled degraded):
#   - no ST7701/DSI timing, no GT911 I2C, no OV5647 CSI DMA,
#   - no PSRAM instruction-fetch vs DMA contention (H1 needs silicon + panel).
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(virtual_fb_demo)
