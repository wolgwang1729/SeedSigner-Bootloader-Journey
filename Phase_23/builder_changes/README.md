# Phase 23 - SeedSigner MicroPython Builder Changes (Slice A)

This directory contains the patches, frozen files, and applicator script to enable headless PSBT signing on the ESP32-P4 under stateless PSRAM execution.

## Overview

In Phase 23 Slice A, we verify the genuine SeedSigner Python application stack (SeedQR decode -> Seed derivation -> PSBT ingestion -> PSBT parsing -> PSBT signing -> UR2 crypto-psbt encoding) without physical display or camera hardware.

Because stdin/UART RX is claimed by the headless virtual framebuffer driver in Phase 18 builds, the headless signing test cannot be driven via interactive serial typing. Instead, we hook into the early startup flow in `stateless_main_src` to execute the signing pipeline automatically, emit the signed UR frames over UART, and verify them on the host.

## Components

1. **`files/frozen_app/`**:
   - `_headless_fixtures.py`: Pre-baked single-input PSBT and 12-word SeedQR fixtures.
   - `_headless_signer.py`: Execution pipeline running `DecodeQR`, `Seed`, `PSBTParser`, `psbt.sign_with`, and `UREncoder`.
2. **`patches/0001-manifest-headless-signer.patch`**:
   - Updates `deps/micropython/mods/new_files/ports/esp32/boards/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43/manifest.py` to freeze `_headless_fixtures.py` and `_headless_signer.py` into the firmware.
3. **`patches/0002-stateless-main-headless-signer.patch`**:
   - Updates `deps/micropython/upstream/ports/esp32/main.c` around `stateless_main_src`: replaces the memory probe loop with `import _headless_signer; _headless_signer.run()`.
4. **`apply_changes.sh`**:
   - Usage: `./apply_changes.sh [target_dir]` to apply.
   - Usage: `./apply_changes.sh --revert [target_dir]` to revert all changes.

## Verification

After applying changes and building the firmware, boot the image in `esp-emu` or on physical silicon. The pipeline prints:
```
[P23] === Phase 23-A Headless PSBT Signing Starting ===
...
[P23] QR 0 ur:crypto-psbt/...
[P23] SUCCESS: full stateless signing flow finished in ... ms
```
The output is verified by `Phase_23/tools/verify_signed_psbt.py`.
