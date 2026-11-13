# Phase 23 - SeedSigner MicroPython Builder Changes (ESP32-S3 Slice A)

This directory contains the patches, frozen files, and applicator script to enable headless PSBT signing on the ESP32-S3 target (`WAVESHARE_ESP32_S3_TOUCH_LCD_35B`) under stateless PSRAM execution.

## Overview

In Phase 23 Slice A, the headless Bitcoin PSBT signing pipeline was ported from the ESP32-P4 to the ESP32-S3. This marks the first execution of the genuine SeedSigner application stack (`embit`, UR/UR2 encoding, multi-input PSBT signing) on the ESP32-S3 stateless bootloader.

## Components

1. **`files/`**:
   - `manifest.py`: Freezes `seedsigner`, `embit`, `urtypes`, `_headless_fixtures.py`, and `_headless_signer.py` into the firmware.
   - `_boot.py`: Early startup hook that invokes `_headless_signer.run()` upon boot.
2. **`patches/0001-s3-mpconfigboard-manifest.patch`**:
   - Updates `mpconfigboard.cmake` for `WAVESHARE_ESP32_S3_TOUCH_LCD_35B` to set `MICROPY_FROZEN_MANIFEST`.
3. **`patches/0002-s3-stateless-shim-extmem.patch`**:
   - Calls `heap_caps_malloc_extmem_enable(16384)` in `stateless_shim.c` after registering the 5 MB PSRAM heap region (`0x3C300000`-`0x3C800000`), allowing MicroPython's allocator (`gc_try_add_heap`) to expand into external memory.
4. **`apply_changes_s3.sh`**:
   - Usage: `./apply_changes_s3.sh [target_dir]` to apply.
   - Usage: `./apply_changes_s3.sh --revert [target_dir]` to revert all changes.

## Verification

Booting the resulting signed image in `esp-emu` produces:
```text
[P23] === Phase 23-A Headless PSBT Signing Starting ===
...
[P23] QR 0 ur:crypto-psbt/...
[P23] SUCCESS: full stateless signing flow finished in 570 ms (free heap: 4912608 B)
```
Output log is recorded in `Phase_23/logs/s3_emu_stateless_sign.txt` and verified via `Phase_23/tools/verify_signed_psbt.py`.
