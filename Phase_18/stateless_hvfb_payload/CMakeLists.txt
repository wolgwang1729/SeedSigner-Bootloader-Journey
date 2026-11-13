# Stateless HVFB payload (Phase 18, slice 1)
#
# ESP-IDF v5.5 app for the ESP32-P4-WIFI6-DEV-KIT (headless) that runs as a
# *signed stateless payload*: the SeedSigner secure loader
# (~/Desktop/seedsigner-esp32-bootloader) verifies the Specter bundle from SD,
# remaps the Cache MMU to PSRAM, and jumps to this image's ELF entry
# (`my_entry_point` in components/stateless_shim).
#
# What it proves (first stateless-display slice):
#   - LVGL renders into a 480x800 RGB565 PSRAM framebuffer while executing
#     from PSRAM (stateless XIP) — no flash execution, no panel hardware;
#   - the frame streams over UART (FB_BEGIN/FB_CHUNK/FB_END) for
#     Phase_18/tools/fb_live.py (same frozen protocol as virtual_fb_demo);
#   - emulated taps (`tap x y`) press on-screen buttons; `result` reports
#     the last selection (durable proof — buttons only flash ~150 ms).
#
# What it does NOT prove yet: SeedSigner app UI (that's the MicroPython
# firmware slice), landscape 800x480, camera/DMA contention (H1).
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(stateless_hvfb_payload)
