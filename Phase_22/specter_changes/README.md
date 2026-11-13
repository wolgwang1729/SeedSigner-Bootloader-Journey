# Phase 22 - Specter-DIY Stateless Overlay (ESP32-P4)

This directory holds everything needed to run the **sandman21vs/specter-diy**
ESP32-P4 port as a stateless payload: built with MicroPython master, wrapped in
a signed bundle, loaded and executed from PSRAM by the Phase 12/13 secure
loader (never through the ESP-IDF second-stage bootloader's app path).

It follows the Phase 18 SeedSigner MicroPython stateless blueprint; the shim is
a direct descendant of that file. The only behavioural difference is the UART
REPL: Phase 18's hvfb console owned stdin, so its shim skipped the RX interrupt.
Here the shim installs MicroPython's RX ISR and keeps the loader's UART
configuration (same approach as the Phase 11/12 shims). Note that the stock
frozen `main.py` runs before the friendly-REPL prompt and blocks in display
init, so the reachable milestone is the UART trace plus the GDB-confirmed
blocker (see `../logs/README.md`), not an interactive prompt.

## Pins

| Component | Repo | Pin |
|---|---|---|
| Payload app | `sandman21vs/specter-diy` branch `esp32-p4-port` | `f54e345` |
| MicroPython | `micropython/micropython` master | `8cf130db34` |
| Loader | `seedsigner-esp32-bootloader` | `976ee3a` |

The loader also carries `Phase_21/loader_changes/emu-flash-payload.patch`
(scratch emu builds only) and `Phase_22/loader_changes/kern-image-compat.patch`,
which already accepts the `specter_esp32p4` platform string and
`/sdcard/specter_esp32p4.bin`.

## Layout

```
specter_changes/
├── stateless_shim/             # new IDF component for the payload
│   ├── CMakeLists.txt          # entry point + --wrap list (incl. OTA)
│   ├── Kconfig                 # CONFIG_STATELESS_PSARAM_EXECUTION marker
│   └── stateless_shim.c        # entry, init passes, PSRAM heap, UART REPL ISR
├── sdkconfig.stateless         # board fragment appended last (stateless build)
├── partitions-stateless.csv    # build-time-only table, auto offsets after 0x20000
├── specter-stateless.patch     # board mpconfigboard.cmake wiring (opt-in flag)
├── micropython-stateless.patch # MicroPython master: 3 stateless changes + qstr build fix
├── hw-diag-main-prints.patch   # hardware-only: print() markers + Specter.start() probe
└── hw-diag-display-markers.patch # hardware-only: ESP_LOGE step markers (+ ST7701 skip)
```

The build script (`../tools/build_specter_stateless_emu.sh`) copies the shim
into `ports/esp32p4/idf_components/stateless_shim/` (already covered by the
board's `EXTRA_COMPONENT_DIRS`) and the two config files into the board
directory, then applies the board patch.

## Sandman board changes

`mpconfigboard.cmake` gains an opt-in block gated on `-DMICROPY_STATELESS=1`:

```cmake
if(MICROPY_STATELESS)
    set(_P4_STATELESS_PARTITIONS_SDKCONFIG ${CMAKE_BINARY_DIR}/sdkconfig.partitions.stateless)
    file(WRITE ${_P4_STATELESS_PARTITIONS_SDKCONFIG}
        "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME=\"${CMAKE_CURRENT_LIST_DIR}/partitions-stateless.csv\"\n")
    list(APPEND SDKCONFIG_DEFAULTS
        ${CMAKE_CURRENT_LIST_DIR}/sdkconfig.stateless
        ${_P4_STATELESS_PARTITIONS_SDKCONFIG})
endif()
```

Appending last is what makes the stateless prerequisites win over
`sdkconfig.board`. The absolute path for the CSV is generated here because
ESP-IDF resolves relative `CONFIG_PARTITION_TABLE_CUSTOM_FILENAME` paths from
`ports/esp32`, not from the board directory.

The board already sets the PSRAM-XIP layout stateless execution needs
(`CONFIG_SPIRAM_XIP_FROM_PSRAM`, `SPIRAM_FETCH_INSTRUCTIONS`,
`SPIRAM_RODATA`), so IROM/DROM land at `0x48000000` and the loader can map
them from PSRAM. `sdkconfig.stateless` adds only the handoff prerequisites:
single-core, PMP split off, no HW stack guard, the loader's `0x20000`
partition-table offset, UART0 at 115200, and PSRAM memtest off.

## MicroPython master patch

`micropython-stateless.patch` makes these changes:

1. **`ports/esp32/main.c`** - skip the frozen `_boot.py` when
   `CONFIG_STATELESS_PSARAM_EXECUTION` is set. There is no flash filesystem to
   mount under stateless execution (the image runs from PSRAM against the
   loader's partition table), and `_boot.py`'s VFS mount would fail. The
   frozen `main.py` still auto-runs below (`pyexec_file_if_exists` resolves
   frozen modules first).
2. **`ports/esp32/esp32_partition.c`** - turn a NULL `esp_partition_t *` into
   `OSError(ENOENT)`. The shim's `esp_ota_get_running_partition` stub returns
   NULL instead of aborting; without the guard, `machine.Partition` would
   dereference NULL.
3. **`ports/esp32/uart.c`** - export `uart_irq_handler` (drop `static`) so the
   shim's `__wrap_uart_stdout_init` can install it without re-initialising the
   loader's UART.
4. **`py/mkrules.cmake` + `py/makeqstrdefs.py`** - build-system fix, not
   stateless-specific: pass the qstr source list through a response file
   (`sources @file`). LVGL contributes >2,000 sources, so the expanded recipe
   exceeds Linux's 128 KB `MAX_ARG_STRLEN` and `/bin/sh` fails with
   `Argument list too long` before `makeqstrdefs.py` runs. The response file is
   generated with `file(GENERATE)` at configure time.

No frozen launcher is needed: sandman's `manifest.py` freezes `src/`, which
includes `main.py`, and MicroPython executes a frozen `main.py` after
`boot.py`/`_boot.py` when running in friendly REPL mode.

## Shim behaviour

`stateless_shim.c` is the Phase 18 shim with the Phase 11/12 UART RX path:

- custom `.data` boot stack and naked `my_entry_point` (`-Wl,-e,my_entry_point`)
- watchdogs disabled, BSS cleared, trap handler installed
- clocks + MMU contexts + both `esp_system_init_fn` passes + constructors
- **PSRAM heap at `0x49080000-0x4A000000`** (16.5 MB offset): the loader
  stages the bundle and image in low PSRAM, so a 2-4 MB MicroPython image can
  reach past 8 MB. The heap starts at 16.5 MB; the build script refuses a
  bundle + image pair that would reach it (the signer tool itself has no such
  check).
- `heap_caps_malloc_extmem_enable(16384)` so plain `malloc` can grow into PSRAM
  (normal `esp_psram_init` never runs under the shim)
- CLIC `_vector_table` / `_mtvt_table` installed before `esp_startup_start_app`
- OTA wraps: `esp_ota_get_running_partition` -> NULL,
  `esp_ota_mark_app_valid_cancel_rollback` -> `ESP_ERR_NOT_FOUND`
- `__wrap_uart_stdout_init` installs MicroPython's RX ISR at the loader's baud
  (no `uart_hal_init`, so pin mux/baud stay as the loader left them)

## Build

```sh
Phase_22/tools/build_specter_stateless_emu.sh          # build + sign + merge + boot in esp-emu
RUN_EMU=0 Phase_22/tools/build_specter_stateless_emu.sh # stop after merge
EMU_GDB=1 RUN_EMU=1 Phase_22/tools/build_specter_stateless_emu.sh # boot with GDB stub on :1234
```

Defaults: the Phase 22 workspace lives under the gitignored `Phase_22/build/`
- sandman clone at `Phase_22/build/specter-p4`, MicroPython at
`Phase_22/build/micropython`, work tree at `Phase_22/build/specter-work`; the
loader is read from the shared loader repo at
`../seedsigner-esp32-bootloader`, IDF v5.5 from `~/esp/esp-idf-v5.5`.
The workspace is disposable: delete it and a rebuild recreates it.
The emu route is the P4 rev-1.3 one (rev0 ROM + virtual eFuse blob), so no
physical eFuse is written and the bundle is injected only into the emulator's
flash image.

## Hardware diagnostics (physical devkit, Oct 20 2026)

The headless devkit has no 4.3" DSI panel and the app logs at
`CONFIG_LOG_DEFAULT_LEVEL_ERROR`, so a stock boot ends silently inside the
display tree. Two hardware-only patches bracket that boundary (applied in
scratch work trees; neither is part of the committed payload):

- `hw-diag-main-prints.patch` - `print()` markers around `display.init(False)`,
  `platform.mount_sdram()` and `Specter.start()`, plus a try/except probe around
  `start()`. The probe catches nothing: the app handles its own exceptions in
  `Specter.handle_exception()` (`print(e)` at `src/specter.py:150`).
- `hw-diag-display-markers.patch` - `ESP_LOGE` step markers through
  `p4board_display_init()`; the second hunk short-circuits `send_st7701_init()`
  so the rest of the app can be exercised without a panel.

Findings (`../logs/specter_hw_*.txt`): the on-chip DSI PHY PLL **does lock**
without a panel, so the emulator's `esp_lcd_new_dsi_bus` stall is emu-only; the
stock payload then blocks inside `send_st7701_init()` on the ST7701 command
sequence (no panel attached). With that sequence
skipped, display init returns, SDRAM mounts, `Specter.start()` is entered, and
the app then follows its own `[Errno 19] ENODEV` error path into a
`SW_CPU_RESET` loop - app-boot territory (Phase 23), not a loader/bundle
failure.

## Expected boot trace

1. loader prints the bundle hash + Specter multisig `PASSED` for
   `specter_esp32p4`
2. JMP zone prints the PSRAM mapping, then the entry point
3. `=== __wrap_call_start_cpu0 ENTERED ===`, init passes, PSRAM heap add,
   `uart_stdout_init: REPL RX ISR installed`
4. frozen Specter `main.py` execution - the two `pyb:` platform stub lines
   (no REPL banner: `main.py` does not return)
5. stop in `esp_lcd_new_dsi_bus()` waiting for the DSI PHY PLL - the emulator's
   headless limit (no LCD/camera/QR in Phase 22). On silicon the PLL locks and
   the stock payload continues to `send_st7701_init()` before blocking; attach
   GDB with `EMU_GDB=1` and the commands in `../logs/README.md` for the emu
   route, or use the diagnostic patches above on hardware.

Result logs: `../logs/specter_emu_stateless_boot.txt` (emu first boot,
virtual-eFuse burn), `../logs/specter_emu_gdb_bt.txt` (emu backtrace at the
stall), and `../logs/specter_hw_stateless_boot.txt` (physical P4 SD boot).

## Verification checklist

- `readelf -h build-W43/micropython.elf` entry is `my_entry_point`
- `readelf -S` / `idf.py size` puts IROM/DROM at `0x48000000` (PSRAM XIP)
- image size < 8 MB (`MAX_FIRMWARE_SIZE`), bundle + image < 16.5 MB
- `CONFIG_STATELESS_PSARAM_EXECUTION=y` in the generated sdkconfig
- `CONFIG_FREERTOS_UNICORE=y`, `CONFIG_ESP_SYSTEM_SINGLE_CORE_MODE=y`
