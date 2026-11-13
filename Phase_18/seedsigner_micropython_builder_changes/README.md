# Phase 18 - SeedSigner MicroPython Builder Changes (ESP32-P4 Stateless + Headless Virtual FB)

Documentation, patch files, and overlay artifacts for the changes required in [`seedsigner-micropython-builder`](https://github.com/SeedSigner/seedsigner-micropython-builder) to build the **Phase 18 Slice 2 SeedSigner MicroPython firmware** on the ESP32-P4.

This produces a signed, completely stateless bundle (`seedsigner_esp32p4.bin`, ~4.52 MB) that boots via the Phase 18 stateless secure bootloader into PSRAM and renders the genuine SeedSigner UI and interactive keyboard headlessly over serial.

---

## Context & Architecture

Phase 18 proved on physical silicon (`ESP32-P4-WIFI6-DEV-KIT` v1.3) that a full SeedSigner MicroPython stack can execute statelessly from PSRAM:
1. **Bootloader Handoff:** Secure Boot V2 -> SD card ingest into PSRAM -> immediate unmount -> Specter secp256k1 multisig verification -> anti-phishing TRNG derivation (4 BIP-39 words) -> Cache-MMU remap (`0x48000000`) -> jump to entry point in SRAM.
2. **Stateless Shim Replay:** Sets up clocks, MMU contexts, and vector tables; relocates the external PSRAM heap past the staged image (16.5 MB offset); enables external allocations for plain `malloc()`; stubs flash-dependent OTA routines; and hands off to `esp_startup_start_app()`.
3. **Headless Virtual FB & Touch:** Replaces hardware DSI panel (`ST7701`) and I2C touch (`GT911`) initialization with a virtual 800x480 RGB565 PSRAM framebuffer streamed via UART chunks (`fb_live.py` on host), taking emulated taps over the console.
4. **Embedded Launcher:** Bypasses flash VFS `_boot.py` and directly instantiates `seedsigner.controller.Controller` to boot the air-gapped wallet UI.

---

## Directory Structure

```
seedsigner_micropython_builder_changes/
├── README.md                # This document
├── apply_changes.sh         # Automated applicator script
├── patches/
│   ├── 0001-builder-root.patch           # Root builder (Makefile, scripts, board overlay)
│   ├── 0002-board-common.patch          # ports/esp32/board_common (virtual FB + init hooks)
│   └── 0003-micropython-upstream.patch  # deps/micropython/upstream (uart, main.c, partitions)
└── files/                   # Exact mirror of all new and modified files
    ├── Makefile
    ├── scripts/build_firmware.sh
    ├── ports/esp32/board_common/
    │   ├── CMakeLists.txt
    │   └── src/
    │       ├── board_init.c
    │       ├── headless_virtual_fb.c
    │       └── headless_virtual_fb.h
    └── deps/micropython/
        ├── mods/new_files/ports/esp32/
        │   ├── partitions-stateless.csv
        │   └── boards/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43/
        │       ├── mpconfigboard.cmake
        │       ├── mpconfigvariant_PRE_REV3_STATELESS.cmake
        │       ├── sdkconfig.board
        │       ├── sdkconfig.stateless
        │       └── stateless_shim/
        │           ├── CMakeLists.txt
        │           ├── Kconfig
        │           └── stateless_shim.c
        └── upstream/ports/esp32/
            ├── esp32_partition.c
            ├── main.c
            ├── uart.c
            └── uart.h
```

---

## Summary of Changes Across 4 Layers

### 1. Root Build System (`Makefile`, `scripts/build_firmware.sh`)
- **Docker Forwarding:** Passed `HEADLESS_VIRTUAL_FB` through `Makefile` into the Docker container.
- **Revision Range Gate:** Updated `scripts/build_firmware.sh` to recognize `PRE_REV3_*` variant names (specifically `PRE_REV3_STATELESS`) for ESP32-P4 rev v1.3 silicon.
- **CMake Definition:** Injected `-DHEADLESS_VIRTUAL_FB=1` when set.

### 2. Peripheral Submodule (`ports/esp32/board_common`)
- **Virtual Display Driver:** Added [`headless_virtual_fb.h`](./files/ports/esp32/board_common/src/headless_virtual_fb.h) and [`headless_virtual_fb.c`](./files/ports/esp32/board_common/src/headless_virtual_fb.c) implementing:
  - An 800x480 RGB565LE framebuffer allocated in PSRAM.
  - A custom LVGL display flush callback that streams chunks over serial (`FB_BEGIN / CHUNK / END`).
  - An emulated `lv_indev` pointer device fed via `tap <x> <y>` and `swipe ...` console commands.
- **Headless Bypasses (`src/board_init.c`):** Under `#ifdef HEADLESS_VIRTUAL_FB`, hardware panel (`ST7701`) and touch controller (`GT911`) initializations are skipped, preventing bus timeouts/crashes on DEV-KIT boards with no screen attached.
- **CMake Wiring:** Conditionally registers `headless_virtual_fb.c` and exports the compiler flag.

### 3. Board Overlay (`deps/micropython/mods/.../WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43/`)
- **New Variant (`PRE_REV3_STATELESS`):** Created `mpconfigvariant_PRE_REV3_STATELESS.cmake` appending `sdkconfig.p4_pre_rev3` and `sdkconfig.stateless`.
- **Stateless Configuration (`sdkconfig.stateless`):**
  - Unicore execution (`CONFIG_FREERTOS_UNICORE=y`, `CONFIG_ESP_SYSTEM_SINGLE_CORE_MODE=y`).
  - PSRAM XIP enabled at `0x48000000` (`CONFIG_SPIRAM_XIP_FROM_PSRAM=y`).
  - Console locked to default UART0 @ 115200 baud (`CONFIG_ESP_CONSOLE_UART_BAUDRATE=115200`).
  - Custom partition table offset at `0x20000` (`CONFIG_PARTITION_TABLE_OFFSET=0x20000`).
  - Custom table `partitions-stateless.csv` using automatic offsets to prevent overlap with bootloader.
- **Stateless Shim (`stateless_shim/`):**
  - **Heap Relocation:** Shifted heap start to **16.5 MB (`0x49080000` to `0x4A000000`)** to prevent overlap with the 4.5 MB firmware image staged in low PSRAM.
  - **External Malloc Enable:** Called `heap_caps_malloc_extmem_enable(16384)` during early boot so standard `malloc()` can allocate from PSRAM, breaking past the 56 KB internal SRAM wall.
  - **UART RX ISR Intercept:** `__wrap_uart_stdout_init()` skips RX ISR registration so the VFS stdin/`hvfb` console owns incoming serial data.
  - **OTA Wrappers:** `--wrap` stubs for `esp_ota_get_running_partition` (returns `NULL`) and `mark_app_valid_cancel_rollback` (returns `ESP_ERR_NOT_FOUND`).
  - **Conditional Compilation:** Exposes `CONFIG_STATELESS_PSARAM_EXECUTION` compile-time marker.

### 4. MicroPython Core Submodule (`deps/micropython/upstream`)
- **UART Conflict Resolution (`ports/esp32/uart.c`, `uart.h`):** Disabled MicroPython's private UART RX ISR so bytes are not stolen from VFS stdin. Set `MICROPY_HW_UART_REPL_BAUD` to 921600 (or matched to console).
- **Embedded Launcher (`ports/esp32/main.c`):** Under `CONFIG_STATELESS_PSARAM_EXECUTION`, skips flash `_boot.py` (which fails without a flash VFS partition) and runs an embedded C-string launcher executing `Controller.get_instance().start()`.
- **Partition NULL Guards (`ports/esp32/esp32_partition.c`):** Added safety check returning `OSError(MP_ENOENT)` instead of aborting when `esp_ota_get_running_partition` returns NULL.

---

## How to Apply the Changes

### Option A: Using the Automated Script (Recommended)
```bash
cd seedsigner_micropython_builder_changes
./apply_changes.sh ~/Desktop/seedsigner-micropython-builder-upstream
```

### Option B: Applying Git Patches Manually
```bash
# 1. Root builder repo
cd ~/Desktop/seedsigner-micropython-builder-upstream
git apply <path-to-phase-18>/seedsigner_micropython_builder_changes/patches/0001-builder-root.patch

# 2. Board common submodule
cd ports/esp32/board_common
git apply <path-to-phase-18>/seedsigner_micropython_builder_changes/patches/0002-board-common.patch

# 3. MicroPython upstream submodule
cd ../../../deps/micropython/upstream
git apply <path-to-phase-18>/seedsigner_micropython_builder_changes/patches/0003-micropython-upstream.patch

# 4. Copy new untracked files from files/
rsync -av <path-to-phase-18>/seedsigner_micropython_builder_changes/files/ ~/Desktop/seedsigner-micropython-builder-upstream/
```

---

## Building the Firmware

Run the build from the builder root directory:

```bash
cd ~/Desktop/seedsigner-micropython-builder-upstream

make docker-build-all \
  BOARD=WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43 \
  BOARD_VARIANT=PRE_REV3_STATELESS \
  HEADLESS_VIRTUAL_FB=1 \
  MP_ALLOW_DIRTY=1 \
  SS_EMBIT_DIR=$PWD/deps/embit \
  SS_APP_DIR=$PWD/deps/seedsigner
```

**Output:**
```
build/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43-PRE_REV3_STATELESS/micropython.bin
```

---

## Signing & Packaging the Payload

Wrap and sign the resulting raw binary into a Specter bundle for the stateless secure bootloader:

```bash
# Using the signing tool:
python3 <path-to-bootloader>/tools/generate_signed_payload.py \
  --bin build/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43-PRE_REV3_STATELESS/micropython.bin \
  --platform seedsigner_esp32p4 \
  --version 1 \
  --privkey <path-to-bootloader>/keys/vendor_secp256k1_test.pem \
  --out build/seedsigner_esp32p4.bin
```

Copy `seedsigner_esp32p4.bin` to the FAT32 microSD card, insert it into the ESP32-P4-WIFI6-DEV-KIT, and monitor execution via:

```bash
python3 tools/fb_live.py --port /dev/ttyACM0 --baud 115200
```
