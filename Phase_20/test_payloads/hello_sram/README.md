# hello_sram - Phase 20 R5a Pure Internal-SRAM Test Payload

`hello_sram` is a standalone, C-only test payload built without SPIRAM XIP. The resulting binary image contains zero `0x48xxxxxx` or `0x40xxxxxx` segments, causing the bootloader to allocate zero MMU entries (`PSRAM MMU footprint: 0 bytes`). The loader performs direct internal SRAM copies and jumps directly to the entry point.

This payload proves:
1. The unmodified production bootloader correctly executes pure-SRAM payloads with zero MMU mapping overhead.
2. The R5c no-JMP loader candidate can boot valid SRAM payloads while cleanly refusing XIP payloads fail-closed.

## Features

- **Pure Internal SRAM Execution:** All segments reside in internal SRAM (`0x4FF00000` / TCM).
- **Interactive UART REPL:**
  - `ping` -> Responds with `PONG`
  - `info` -> Prints free internal heap capacity and FreeRTOS tick count

## Build Instructions (ESP-IDF v5.5)

Due to ESP-IDF v5.5 RAM-type application linking rules, both `CONFIG_APP_BUILD_TYPE_RAM=y` and `CONFIG_APP_BUILD_TYPE_PURE_RAM_APP=y` are required:

```bash
# Set up ESP-IDF environment
source ~/esp/esp-idf-v5.5/export.sh

# Build ELF
idf.py set-target esp32p4
idf.py build

# Generate binary image manually (IDF omits .bin generation for RAM apps)
python3 -m esptool --chip esp32p4 elf2image \
  --flash_mode dio --flash_freq 80m --flash_size 16MB \
  -o build/hello_sram.bin build/hello_sram.elf
```

## Wrap into Specter Bundle

```bash
# Wrap and sign with test key
python3 ../../tools/sign_multisig.py \
  --key ../keys/r4_throwaway_1.pem \
  --platform seedsigner_esp32p4 \
  --version 1 \
  build/hello_sram.bin build/hello_sram_esp32p4.bin
```

Upload `hello_sram_esp32p4.bin` to microSD as `seedsigner_esp32p4.bin` via the RAM SD uploader or direct card write.
