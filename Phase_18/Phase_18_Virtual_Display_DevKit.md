# Phase 18: Headless Display + Touch - The DEV-KIT as a Virtual 4.3" Panel

- **Date:** October 16, 2026
- **Author:** Mayank (wolgwang)
- **Project:** SeedSigner Secure Boot — Independent Continuation
- **Status:** COMPLETE (One-off Headless Test / Degraded) - **DEPRECATED / NOT CARRIED FORWARD**
- **Hardware:** ESP32-P4-WIFI6-DEV-KIT only (headless, v1.3 silicon, 16 MB flash)
- **Scope Notice:** This virtual framebuffer and UART streaming tool was purely a one-off feasibility test to prove PSRAM stateless execution and UI navigation headlessly on silicon. It is **NOT** carried forward into future phases (it is not real hardware, and waiting ~12-95 s per frame is not a substitute for actual DSI/RGB panel hardware). Future phases will test on real display hardware once procured.

---

## 1. Overview

Phases 1 through 17 completed the initial project deliverables, establishing the stateless secure bootloader architecture across both the ESP32-P4 (Phases 9-14) and the ESP32-S3 (Phases 15-17). In Phase 17, the S3 was brought to a pure SD-card stateless boot with full anti-phishing flash hardening and zero flash runtime footprints.

Entering this **Independent Continuation** (in preparation for the Bitshala Fellowship), the primary milestone was bringing the full SeedSigner user experience (LVGL graphical user interface, touchscreen interaction, and cryptographic signing workflows) onto the high-performance **ESP32-P4**. However, due to critical hardware supply chain shortages in India, compatible 4.3" MIPI-DSI LCD panels (`ST7701`) and capacitive touch controllers (`GT911`) were completely unavailable locally.

To avoid blocking development while hardware procurement was underway, **Phase 18** implemented a virtual display and touch emulator over the serial console. This allowed testing and de-risking the critical software layers on physical silicon:
1. **Stateless PSRAM Framebuffer Execution:** Proving that LVGL 9.5 can allocate draw buffers and render full 800×480 RGB565 frames purely from external PSRAM while executing through the stateless loader's Cache MMU remap without triggering bus arbitration faults.
2. **Interactive UI Navigation Headlessly:** Intercepting touch events via custom pointer driver (`lv_indev`) fed by serial commands (`tap`, `swipe`), enabling full walkthroughs of genuine SeedSigner screens (Home → Seeds → Load a Seed → Seed Word #1 keyboard).
3. **End-to-End Cryptographic Chain:** Verifying that a signed Specter MicroPython bundle loaded from SD can initialize the virtual display stack and execute securely without any display hardware attached.

> [!WARNING]
> **Scope & Deprecation Notice:**
> This headless virtual display emulator was an interim engineering bridge. Serial frame transport requires ~12 s (at 921,600 baud) to ~95 s (at 115,200 baud) per snapshot, which cannot model real-time MIPI-DSI or camera timing. This harness is **strictly deprecated and not carried forward** into subsequent fellowship phases. Future phases will execute directly on physical display modules.

---

## 2. End-to-End System Architecture & Virtual Display Pipeline

The complete Phase 18 pipeline establishes a bridge between the physical ESP32-P4 silicon and the host workstation:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      ESP32-P4 Hardware / ROM Boot                       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│           ESP-IDF 2nd-Stage Bootloader (@ 0x2000, Secure Boot V2)       │
│   - Hardware / virtual eFuse verification of RSA-3072 signature         │
│   - Verified OK → loads factory loader app from @ 0x30000               │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│           Stateless Secure Loader (factory app @ 0x30000)                │
│                                                                         │
│   1. Mounts FAT32 SD card (4-bit SDMMC, on-chip LDO4 power)             │
│   2. Reads /sdcard/seedsigner_esp32p4.bin into PSRAM buffer             │
│   3. UNMOUNTS SD CARD IMMEDIATELY (Anti-TOCTOU protection)               │
│   4. Specter secp256k1 multisig verification (platform, pl_ver, sig)    │
│   5. Anti-Phishing: Hashes random_fill -> Displays 4 BIP-39 words       │
│   6. Stages IROM/DROM into PSRAM fake_flash; maps MMU @ 0x48000000      │
│   7. Direct copies internal SRAM segments; jumps to IRAM JMP zone       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                 IRAM JMP Zone & Stateless Shim Handoff                  │
│   - Masks interrupts, tears down watchdogs, disables PMP                │
│   - Rewrites Cache MMU entries (PSRAM physical -> 0x48000000 XIP window)│
│   - Jumps to payload entry point (my_entry_point)                       │
│   - Stateless Shim: Sets up CLIC vectors, enables PSRAM heap,           │
│     stubs flash-dependent functions, calls esp_startup_start_app()      │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│            SeedSigner Application & Headless Virtual FB Engine          │
│                                                                         │
│   - MicroPython VM / C App initializes LVGL 9.5                         │
│   - headless_virtual_fb: Creates virtual display (800x480 RGB565LE)     │
│   - Draw buffers allocated in PSRAM; flush_cb copies to master FB       │
│   - Custom lv_indev pointer driver registered to receive emulated taps  │
│   - UART Serial Streamer: Encodes frame into Base64 chunks              │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ UART (115200 / 921600 baud)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│             Host Development Workstation (Live UI Emulator)             │
│                                                                         │
│   - fb_live.py: Live GUI window reassembles FB_BEGIN / CHUNK / END      │
│   - Renders progressive scanlines with CRC32 integrity validation       │
│   - User click/drag translates to 'tap x y' / 'swipe ...' commands      │
│   - Terminal mirror outputs device logs, boot times, and tap results   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Repository Inventory & Component Layout

The artifacts developed for this phase are organized as follows:

| Path | Purpose & Contents |
|---|---|
| [`virtual_fb_demo/`](./virtual_fb_demo/) | Standalone ESP-IDF v5.5 app proving the baseline seam: LVGL transcript screen (UNSCII-8 green-on-black) rendered via custom `flush_cb` into a 480×800 RGB565LE PSRAM framebuffer. SD dump (`fb0.raw`/`.ppm`) + UART stream + console (`help\|info\|dump\|save\|clear`). Runs from flash (NOT stateless; flash writes only, no eFuse). |
| [`board_common_virtual_fb/`](./board_common_virtual_fb/) | **Device-Side Headless Driver:** `headless_virtual_fb.h/.c` + `README.md`. Virtual display (`lv_display_create` + PSRAM draw bufs + memcpy `flush_cb`) + pointer `lv_indev` fed by `tap`/`swipe` console lines + `FB_BEGIN/CHUNK/END` streamer + `result` readout hook. Supports both 480×800 portrait and 800×480 landscape (`hvfb_init_ex`). RAM + UART only. |
| [`stateless_hvfb_payload/`](./stateless_hvfb_payload/) | **Slice 1 C Test Harness:** Signed ESP-IDF test app (`stateless_shim` + `hvfb_stateless.c` without `esp_lvgl_port`). UI: transcript + 2×2 `BTN_A..D` pad, 480×800, 115,200 baud. `build_sign.sh` produces signed bundle `build/seedsigner_esp32p4.bin`. Hardware-proven (§5). |
| [`tools/fb_live.py`](./tools/fb_live.py) | **Live Screen Emulator Window:** Opens console serial port, sends `dump`, reassembles `FB_BEGIN/CHUNK/END` live (either geometry), and paints progressive scanlines. Command entry sends console lines; click = `tap x y`, drag = `swipe ...`. Mirrored terminal logging, stall watchdog (8 s), bounded poll (200 events / 40 rows per tick), exclusive port locking. |
| [`tools/fb_viewer.py`](./tools/fb_viewer.py) | Stdlib-only snapshot viewer: `--raw` / `--serial-log` / `--selftest` → CRC check → `.png` (+ optional `.ppm`, `--show` via tkinter). Supports both 480×800 and 800×480 geometries. |
| [`tools/fb_capture.py`](./tools/fb_capture.py) | Serial helper predating the live window (interactive terminal session with log capture). |
| [`tests/`](./tests/) | 26 host pytest cases requiring no hardware: 4 viewer tests (geometry, PNG roundtrip, serial reassembly, CRC validation) + 22 live emulator tests (protocol parsing, defragmenting stream reassembly, tap/swipe roundtrips, coordinate clamping, exclusive port locks). |
| [`seedsigner_micropython_builder_changes/`](./seedsigner_micropython_builder_changes/) | Builder overlay artifacts, unified git patches (`patches/`), mirrored overlay tree (`files/`), and `apply_changes.sh` script to reproduce the Slice 2 stateless SeedSigner MicroPython build (`PRE_REV3_STATELESS` variant with `HEADLESS_VIRTUAL_FB=1`). |
| [`fb_stateless_hvfb.png`](./fb_stateless_hvfb.png) | Hardware proof snapshot: Slice 1 C harness transcript + button pad (CRC-OK `0x9F1DB89A`). |
| [`fb_stateless_home.png`](./fb_stateless_home.png) | Hardware proof snapshot: Slice 2 real SeedSigner Home screen (CRC-OK `0x42312D2B`). |
| [`fb_stateless_load_seed.png`](./fb_stateless_load_seed.png) | Hardware proof snapshot: Slice 2 real SeedSigner Load-a-Seed screen (CRC-OK `0x53C11CF0`). |

---

## 3. Virtual Display & Touch Protocol Specification

The serial protocol is designed for robustness over lossy, buffered UART links. It supports two distinct geometries matching the SeedSigner hardware profiles:
- **Portrait (480×800):** ST7701 console bring-up and `touch_test` diagnostics.
- **Landscape (800×480):** Genuine SeedSigner 4.3" user interface.

Both geometries comprise exactly **768,000 raw bytes** (16-bit RGB565LE, row-major, top-left origin), divided into exactly **4,000 UART transmission chunks** (192 bytes per chunk → 256 Base64 characters).

### 3.1 Packet Framing Protocol

```
Device → Host:  FB_BEGIN <width> <height> <total_len> <crc32_hex>
                FB_CHUNK <seq> <base64_data>   (repeated 4000 times, seq 0..3999)
                FB_END <total_chunks>

Host → Device:  dump
                tap <x> <y>
                swipe <x0> <y0> <x1> <y1>
                info
                result
```

### 3.2 Protocol Semantics

- `FB_BEGIN`: Signals start of frame transmission, providing resolution, expected payload byte count (768,000), and expected CRC32.
- `FB_CHUNK`: Transmits 192 bytes of binary pixel data encoded as 256 Base64 characters with a 0-indexed sequence number.
- `FB_END`: Confirms frame completion with total chunk count (4,000). The host reassembles the buffer and validates the calculated CRC32 against `FB_BEGIN`.
- `tap <x> <y>`: Injects a 150 ms simulated press-and-release touch pulse at the specified firmware pixel coordinates (in GT911 touch coordinate space).
- `swipe <x0> <y0> <x1> <y1>`: Injects an 8-step linear press-move-release gesture spanning ~320 ms.
- `result`: Queries the last screen selection recorded by the application. Because LVGL button states flash active for only ~150 ms, `result` provides durable proof of touch registration.
- **Baud Rates:**
  - `115200` baud: Standard bootloader bring-up speed (~95 s per frame transfer).
  - `921600` baud: High-speed transfer (~12 s per frame transfer) enabled via Custom UART0 routing on `U0TXD=37` / `U0RXD=38`, matched with `MICROPY_HW_UART_REPL_BAUD=921600`.

---

## 4. Host Emulator & Test Infrastructure

The host tooling provides interactive visual feedback and automated validation without requiring attached hardware.

### 4.1 Live Screen Emulator (`tools/fb_live.py`)
The live emulator connects directly to the serial console and coordinates bidirectional communication:
- **Progressive Rendering:** Dynamically parses incoming `FB_CHUNK` lines and paints progressive scanlines directly onto a Tkinter canvas.
- **Dynamic Geometry Adjustment:** Automatically detects and re-shapes the window between portrait (480×800) and landscape (800×480) upon receiving `FB_BEGIN`.
- **Interactive Mouse Mapping:** Clicking the canvas computes the pixel coordinates and transmits `tap x y`; dragging emits `swipe x0 y0 x1 y1`. Sent commands are mirrored to the interactive entry box.
- **Concurrency & Robustness:**
  - *Exclusive Port Locking:* Locks the serial port to prevent split-stream data corruption from concurrent monitor instances.
  - *Bounded Event Dispatch:* Restricts processing to at most 200 events / 40 rows per UI tick, preventing post-reset terminal bursts from wedging the GUI loop.
  - *Stall Watchdog:* Re-issues `dump` if no packets are received within 8 seconds of initialization.
  - *Terminal Mirroring:* All non-frame console output (boot logs, exceptions, timings) is mirrored to stdout.

### 4.2 Automated Test Suite (`tests/`)
A complete 26-test pytest suite verifies the protocol stack entirely in software:
- **Snapshot Viewer Tests (4 cases):** Geometry detection, PNG round-trip serialization, serial stream reassembly, and corrupted-frame CRC rejection.
- **Live Emulator Tests (22 cases):** Terminal prefix stripping, defragmentation of split/interleaved lines under tap echo, progressive chunk assembly straddling boundaries, coordinate clamping, exclusive file locking, and bounded event loop stability under message bursts.

---

## 5. Slice 1: Stateless C Harness Implementation & Silicon Verification

Slice 1 proved the fundamental architectural seam: executing the stateless secure loader on the ESP32-P4, remapping external PSRAM via the MMU, and running an LVGL C application that streams frames and accepts touch input.

### 5.1 C Harness Design (`stateless_hvfb_payload`)
The test payload was constructed as a standalone ESP-IDF v5.5 application:
- **Linker Contract:** Linked with custom entry point `my_entry_point` at `0x4FF015F0` (internal SRAM direct-copy target) and IROM/DROM segments placed in the `0x48000000` PSRAM XIP window.
- **Stateless Shim Integration:** Includes `stateless_shim.c` to wrap `call_start_cpu0()`, establish CLIC interrupt vector tables, initialize the PSRAM heap (25 MB free), and bypass hardware re-initialization.
- **UI Structure:** Renders a 480×800 portrait interface featuring a text transcript window and a 2×2 button pad (`BTN_A`, `BTN_B`, `BTN_C`, `BTN_D`).

### 5.2 Silicon Verification on ESP32-P4 DEV-KIT (October 15, 2026)
The payload was signed with the Phase 12 test keys and bundled into `Phase_18/build/seedsigner_esp32p4.bin` (539,200 bytes). Booted on physical ESP32-P4 silicon:

```text
I (290) secure_boot_v2: Verifying with RSA-PSS...
I (296) secure_boot_v2: Signature verified successfully!
I (304) boot: Loaded app from partition at offset 0x30000
I (310) secure_boot_v2: enabling secure boot v2...
I (314) secure_boot_v2: secure boot v2 is already enabled, continuing..
I (340) SEEDSIGNER_LOADER: SeedSigner Secure Loader - ESP32-P4
I (350) SEEDSIGNER_LOADER: Mounting SD card (4-bit SDMMC, LDO4)...
I (410) SEEDSIGNER_LOADER: Loaded 539200 bytes from /sdcard/seedsigner_esp32p4.bin
I (412) SEEDSIGNER_LOADER: Unmounting SD card before verification (TOCTOU-safe)...
I (415) SEEDSIGNER_LOADER: Specter bootloader section detected (version 1)
I (430) SEEDSIGNER_LOADER: Performing secp256k1 multisig verification...
I (445) SEEDSIGNER_LOADER: Signature verification PASSED!
I (450) anti_phish: Erasing and filling 6094848 bytes with TRNG data...
I (4890) anti_phish:   ANTI-PHISHING PROOF: ritual one enlist weasel
I (4895) SEEDSIGNER_LOADER: Image OK: 6 segments, entry=0x4FF015F0
I (4900) SEEDSIGNER_LOADER: JMP[1..7] MMU remap -> entering payload...
=== __wrap_call_start_cpu0 ENTERED ===
[SHIM] Setting up CLIC vectors and clocks...
[SHIM] Adding 25 MB PSRAM to heap allocator...
[HVFB-S] Initializing headless virtual display (480x800)...
[HVFB-S] console ready
```

### 5.3 Touch Interaction & Frame Capture
- **Touch Verification:**
  - Injected command: `tap 122 654` → Device registered: `pressed BTN_A (#0)` → Output: `result: button_selected #0 'BTN_A'`
  - Injected command: `tap 358 746` → Device registered: `pressed BTN_D (#3)` → Output: `result: button_selected #3 'BTN_D'`
- **Frame Capture:**
  - Sent `dump` command → Reassembled 4,000/4,000 chunks → `crc=9F1DB89A OK`.
  - Snapshot saved as [`fb_stateless_hvfb.png`](./fb_stateless_hvfb.png), confirming pixel-perfect rendering of the LVGL UI executing purely from PSRAM.

---

## 6. Slice 2: Full SeedSigner MicroPython Stateless Execution & UI Navigation

Slice 2 achieved the primary milestone: booting the full, genuine SeedSigner MicroPython operating system statelessly on the ESP32-P4 and interactively driving the actual application UI through the virtual display.

### 6.1 Builder Integration & MicroPython Adaptations
Firmware builds were developed within `seedsigner-micropython-builder-upstream` using a new build target:
- **Variant `PRE_REV3_STATELESS`:** Configured unicore FreeRTOS (`MP_TASK_COREID (0)`), disabled PMP partitioning, pinned console UART to 115,200 baud, and targeted the relocated partition table (`0x20000`).
- **Stateless Shim Transplant:** Integrated the `stateless_shim` into `ports/esp32/boards/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43/stateless_shim/`.
- **Runtime Shim Stubs:**
  - Wrapped `uart_stdout_init` as a no-op to prevent MicroPython from installing its default UART ISR, which steals serial input from the `hvfb` console.
  - Implemented stubs returning NULL / `ESP_ERR_NOT_FOUND` for `esp_ota_get_running_partition` and `mark_app_valid_cancel_rollback` (since PSRAM virtual addresses do not exist in the flash partition table).
  - Added compile-time marker `CONFIG_STATELESS_PSRAM_EXECUTION` to bypass the stock flash filesystem mount (`_boot.py` inisetup loop) and execute an embedded C-string launcher.

### 6.2 Silicon Verification on ESP32-P4 DEV-KIT (October 15, 2026)
The firmware was packaged into a signed Specter bundle `seedsigner_esp32p4.bin` (4,523,600 bytes, SHA `938bff9a`, 7 XIP segments) and booted on physical silicon:

```text
I (294) secure_boot_v2: Signature verified successfully!
I (310) SEEDSIGNER_LOADER: Loaded 4523600 bytes from /sdcard/seedsigner_esp32p4.bin
I (312) SEEDSIGNER_LOADER: Unmounting SD card before verification (TOCTOU-safe)...
I (330) SEEDSIGNER_LOADER: Specter secp256k1 multisig verification PASSED!
I (335) anti_phish:   ANTI-PHISHING PROOF: ritual one enlist weasel
I (340) SEEDSIGNER_LOADER: Remapping MMU and jumping to payload entry @ 0x4FF05380...
=== __wrap_call_start_cpu0 ENTERED ===
[SHIM] Initializing PSRAM heap (15.5 MB free @ 0x49080000)...
[SHIM] Enabling extmem allocations for malloc cascade...
[HVFB] Landscape display initialized: 800x480 RGB565LE
[boot-ms] main.py start
[boot-ms] SeedSigner Controller initialized in 51200 ms
Controller.start() invoked
```

### 6.3 End-to-End Navigation Walkthrough
The genuine SeedSigner application was driven through multi-step interactive navigation using the virtual display emulator:
1. **Home Screen:**
   - App booted past the animated splash screen to the genuine **Home Menu** (Scan, Seeds, Tools, Settings).
   - Captured frame validated: `crc=42312D2B OK` → [`fb_stateless_home.png`](./fb_stateless_home.png).
2. **Screensaver & Wake:**
   - Allowed the screen to idle until the screensaver activated (bouncing pill animation).
   - Injected `tap 400 240` → Screen immediately woke up and returned to the Home menu.
3. **Seeds Menu:**
   - Injected `tap 400 210` (Seeds button) → Navigated to the **Seeds Screen**.
4. **Load a Seed:**
   - Injected `tap 400 160` (Load a Seed button) → Navigated to the **Load a Seed Screen**.
   - Captured frame validated: `crc=53C11CF0 OK` → [`fb_stateless_load_seed.png`](./fb_stateless_load_seed.png).
5. **Seed Word #1 Keyboard:**
   - Injected `tap` on Mnemonic entry → Displayed the interactive **Seed Word #1 Keyboard**, proving complete end-to-end UI interaction through the stateless bootloader.

---

## 7. Technical Challenges, Root Cause Analysis & Solutions

During the bring-up of the headless virtual display and MicroPython stack, 34 distinct technical issues were encountered and resolved. They are categorized below:

### 7.1 Build & Toolchain Challenges
1. **Bootloader Chip Revision Gate:** ESP-IDF v5.5 bootloaders default to chip revision v3.1+; the physical DEV-KIT board has v1.3 silicon (`requires chip revision [v3.1-v3.99]`).
   - *Fix:* Configured `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y` in application configs and `BOARD_VARIANT=PRE_REV3` in firmware builds.
2. **32 MB Flash Header on 16 MB Silicon:** The prebuilt dist config assumed 32 MB flash, causing `Detected size smaller... Probe failed` during boot.
   - *Fix:* Passed `--flash_size 16MB` to `esptool.py` and updated board configurations to 16 MB.
3. **Component Name Collision:** ESP-IDF names components by directory name; the build looked for `esp-board-common` while the local directory was `board_common`.
   - *Fix:* Established a Docker mirror directory named `esp-board-common`.
4. **Missing Nested Submodules:** `k_quirc` and `secp256k1-zkp` were uninitialized in clean trees.
   - *Fix:* Executed recursive git submodule initialization.
5. **Camera Component Include Path:** `ov02c10` driver failed to resolve because `EXTRA_COMPONENT_DIRS` did not scan component subdirectories.
   - *Fix:* Appended `../../components` to `EXTRA_COMPONENT_DIRS`.
6. **Bootloader Size Overflow:** Adding components grew the bootloader past `0x6000`, causing partition table collisions.
   - *Fix:* Relocated the partition table to `0x10000` and updated partition offsets accordingly.
7. **Kconfig UART Baud Rate Drop:** `ESP_CONSOLE_UART_BAUDRATE` was silently ignored unless `ESP_CONSOLE_UART_CUSTOM` was set.
   - *Fix:* Enabled `ESP_CONSOLE_UART_CUSTOM` and mapped Custom UART0 to `U0TXD=37` / `U0RXD=38`.

### 7.2 MicroPython & Runtime Execution
8. **`inisetup` Corrupted Filesystem Loop:** MicroPython's stock `_boot.py` attempted to FAT-mount the partition table; finding a LittleFS image or blank space caused a format loop.
   - *Fix:* Erased the VFS flash sector and deployed `/main.py` directly for bring-up.
9. **Stale Flash Artifacts:** Residual partition tables from prior tests caused conflicting address mappings.
   - *Fix:* Performed `erase_flash` before flashing new partition configurations.
10. **MicroPython UART ISR Stealing Input:** MicroPython's `uart_irq_handler` drained the UART hardware FIFO into its private buffer, preventing VFS stdin from receiving `tap` or `dump` commands.
    - *Fix:* Applied a build patch to bypass UART RX ISR registration, routing serial input directly to the `hvfb` console.
11. **PSRAM Heap / Image Staging Overlap:** The shim's initial heap base (`0x48800000`, 8 MB) overlapped the tail of the loader-staged 4.5 MB image (`paddr 0x470000` to `0x8C0000`), causing `malloc` to return executable code bytes as pointers.
    - *Fix:* Relocated the heap base to 16.5 MB (`0x49080000`, providing ~15.5 MB heap) and added a build-time assertion ensuring `bundle + image < 16.5MB`.
12. **The 56 KB Malloc Wall:** Plain `malloc` calls failed with `MemoryError` during Python imports while PSRAM framebuffer allocations succeeded.
    - *Fix:* Identified that `heap_caps_malloc_extmem_enable()` was never called because `esp_psram_init()` is bypassed by the shim; invoked it manually in the shim.
13. **OTA Partition Abort:** MicroPython app initialization queried the running partition via `esp_ota_get_running_partition()`, which aborts when running from PSRAM virtual addresses.
    - *Fix:* Implemented `--wrap` stubs returning NULL / `ESP_ERR_NOT_FOUND` and guarded partition lookups.
14. **Submodule Syntax Drift:** The local app tree had drifted and included PEP-701 f-string syntax that MicroPython 1.27 cannot freeze.
    - *Fix:* Pinned builds strictly to the verified `deps/seedsigner` and `deps/embit` submodules.
15. **Docker Variable Dropping:** `make` failed to forward `HEADLESS_VIRTUAL_FB=1` through Docker, compiling firmware without the virtual display driver.
    - *Fix:* Forwarded environment variables in `Makefile` and explicitly appended `-DHEADLESS_VIRTUAL_FB=` in `build_firmware.sh`.
16. **Missing Header File:** `py/vstr.h` was missing in the MicroPython tree; resolved to `py/misc.h`.
17. **Frozen Module Lookup Miss:** Frozen `stateless_main` failed runtime lookup despite correct manifest registration.
    - *Fix:* Embedded the startup launcher as a C string executed via `pyexec_vstr()`.

### 7.3 Host Tooling & Serial Synchronization
18. **Serial Port Splitting:** Running two host tool instances concurrently split incoming byte streams.
    - *Fix:* Enforced exclusive file locking (`exclusive=True`) on port open.
19. **Device Boot Race:** Host `dump` commands sent immediately on startup raced device initialization.
    - *Fix:* Implemented an 8-second silence watchdog that automatically re-triggers `dump`.
20. **GUI Starvation on Burst Input:** High-volume serial bursts starved the Tkinter UI thread.
    - *Fix:* Bounded UI polling to a maximum of 200 events and 40 scanlines per tick.
21. **Terminal Blindness:** Errors and tracebacks were swallowed by the GUI.
    - *Fix:* Mirrored all non-protocol console lines directly to the host terminal.
22. **UI Usability:** Initial emulator window was too small and difficult to interact with.
    - *Fix:* Enforced `--scale 1` full-size rendering with enlarged font and autofocus on the command entry box.
23. **Non-Latching Buttons:** LVGL buttons flash active for only ~150 ms, making visual latching impossible at slow baud rates.
    - *Fix:* Implemented the `result` query command to provide durable verification of registered button taps.
24. **Torn Animation Frames:** Dumps taken during UI transitions showed torn scanlines.
    - *Fix:* Added `--keep-bad` flag to save incomplete or transitioning frames for diagnostic review.
25. **Missing SD Card Wait:** The UI loop stalled in `microsd.poll()` when no card was inserted.
    - *Fix:* Inserted a formatted FAT32 SD card into the slot.

### 7.4 Physical Hardware & Flashing Nuances
26. **Stale Virtual eFuse Store:** Residue in the virtual-eFuse flash sector (`0x28000`) caused the bootloader to loop 290× with `Sig block 0 signed with untrusted key`.
    - *Fix:* Erased flash sector `0x28000` via `esptool.py`, allowing first boot to re-provision the virtual eFuse digest.
27. **SD Card Uploader Baud Rate Failure:** RAM-based UART uploader failed on the final segment at 921,600 baud.
    - *Fix:* Enforced `--rom-baud 115200` and performed a `remove` operation prior to uploading new bundles.
28. **Residual SD Card Files:** Previous test binaries on the SD card caused version mismatch warnings; deleted stale artifacts before testing.
29. **Watchdog Trigger During Flash Fill:** Generating 6 MB of TRNG data on first boot triggered an idle watchdog warning; resolved cleanly upon completion.
30. **Serial Reset on Port Open:** Opening `/dev/ttyACM0` triggers DTR/RTS reset on the CH343 USB-UART chip.
    - *Fix:* Ensured all multi-step test assertions execute within a single continuous serial session, allowing ~10 s post-reset settling time.
31. **App Import Profiling Detour:** A 51-second controller import time initially appeared to be a timer tick bug; timing analysis confirmed it was normal Python bytecode interpretation and garbage collector expansion on single-core RISC-V.
32. **Host Esptool Version Gate:** `sd_upload.py` rejected esptool versions newer than 4.12.0.
    - *Fix:* Sourced the ESP-IDF v5.5 environment (`export.sh`) prior to execution.
33. **Sudo SD Card Mount Failure:** Automated mount scripts failed on permissions.
    - *Fix:* Used `udisksctl mount -b /dev/sdb1` for unprivileged mounting.
34. **Build Script Chip Revision Gate:** Builder scripts strictly checked for `BOARD_VARIANT=PRE_REV3`.
    - *Fix:* Relaxed the regex to match `PRE_REV3_*`.

---

## 8. Upstream Recommendations & Architectural Insights

The following findings were documented and flagged for upstream maintainers (Keith Mukai / SeedSigner / MicroPython):
1. **Component Path Inclusion:** Local IDF application templates should include `../../components` in `EXTRA_COMPONENT_DIRS` to avoid manual path workarounds.
2. **LVGL 9.5 vs 9.6 Compatibility:** Public text shaping APIs (`lv_text_ap_calc_bytes_count`, `lv_text_ap_proc`) were removed in LVGL 9.6; upstream components should standardize on managed LVGL 9.5.0 headers.
3. **MicroPython `_boot.py` LittleFS Handling:** Upstream `_boot.py` scripts should detect and mount LittleFS images gracefully rather than entering a destructive formatting loop.
4. **UART Ingestion Architecture:** Upstream MicroPython ports should implement a mechanism allowing native VFS stdin drivers to coexist with the MicroPython REPL ISR.

---

## 9. Scope Boundaries & Honest Limits

To maintain absolute engineering integrity, the boundaries of Phase 18 are explicitly stated:
- **No Physical Display or Camera Timing:** Because no MIPI-DSI panel or MIPI-CSI camera was attached, bus contention (such as AHB/AXI bus matrix saturation under concurrent DMA) was not measured on silicon.
- **Low Frame Rate:** The serial virtual display is a slow snapshot inspector (~0.08 fps at 921,600 baud; ~0.01 fps at 115,200 baud), not an interactive video output.
- **Temporary Sacrifices:** MicroPython UART REPL input was disabled to allow touch command ingestion; QR scanning flows were parked due to lack of camera hardware.
- **Zero Irreversible Actions:** All hardware tests were conducted using virtual eFuses (`CONFIG_EFUSE_VIRTUAL=y`); no physical fuses were burned.
- **Retired Status:** As stated, this virtual display harness was strictly an interim feasibility test to unblock software development and is **not carried forward into future phases**.

---

## 10. Runbook & Artifacts

### 10.1 Silicon Reproduction Runbook

1. **Flash Stateless Bootloader:**
   ```bash
   cd ~/Desktop/seedsigner-esp32-bootloader
   ./run.sh --target esp32p4 flash
   ```
2. **Deploy Signed Bundle to FAT32 SD Card:**
   ```bash
   # Copy signed bundle (test keys) to microSD root
   cp build/seedsigner_esp32p4.bin /media/$USER/<SDCARD>/seedsigner_esp32p4.bin
   sync
   ```
3. **Launch Host Screen Emulator:**
   ```bash
   python3 tools/fb_live.py --port /dev/ttyACM0 --baud 115200
   ```
4. **Interactive Verification:**
   - Wait ~10 s for bootloader verification, anti-phishing proof, and app startup.
   - Screen will render the SeedSigner Home menu.
   - Click UI buttons to inject taps; verify navigation into Seeds and Load-a-Seed menus.

### 10.2 Deliverable Artifacts

- [`Phase_18_Virtual_Display_DevKit.md`](./Phase_18_Virtual_Display_DevKit.md) - Main Phase 18 engineering documentation.
- [`board_common_virtual_fb/`](./board_common_virtual_fb/) - C virtual display driver, draw buffer manager, and touch indev.
- [`stateless_hvfb_payload/`](./stateless_hvfb_payload/) - Slice 1 signed test application and stateless shim harness.
- [`seedsigner_micropython_builder_changes/`](./seedsigner_micropython_builder_changes/) - MicroPython build system patches, overlay files, and reproduction script.
- [`tools/fb_live.py`](./tools/fb_live.py) - Progressive live serial screen emulator with touch injection.
- [`tools/fb_viewer.py`](./tools/fb_viewer.py) - Snapshot viewer and CRC validation utility.
- [`tests/`](./tests/) - 26 pytest automated test cases validating protocol robustness.
- [`fb_stateless_hvfb.png`](./fb_stateless_hvfb.png) - Proof snapshot: Slice 1 C harness UI.
- [`fb_stateless_home.png`](./fb_stateless_home.png) - Proof snapshot: Slice 2 SeedSigner Home menu.
- [`fb_stateless_load_seed.png`](./fb_stateless_load_seed.png) - Proof snapshot: Slice 2 SeedSigner Load-a-Seed menu.
