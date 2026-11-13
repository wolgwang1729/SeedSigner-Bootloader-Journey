# Phase 22 - Execution Logs

| File | What it is |
|---|---|
| `kern_emu_first_boot.txt` | Baseline boot of **unmodified** Kern in esp-emu. Kern `7cdd258`, ESP-IDF v6.1, `wave_43` (pre-v3), `CONFIG_EFUSE_VIRTUAL=y`; real ROM + 2nd-stage bootloader + signed app. Reaches `app_main()`, `esp_lvgl:adapter: LVGL adapter initialized successfully`, `wave_43: MIPI DSI PHY Powered on`, then no further UART before the 180 s timeout. This is the absent-DSI-panel blocker, not a loader failure. |
| `kern_stateless_loader_emu.txt` | First stateless-loader attempt (secure-signed Kern image, 8 segments). The loader verifies the Specter bundle and enters JMP, then faults at `PC=0x50108080`: Kern's 36-byte RTC segment overwrote the loader's cache-off `do_mmu_mapping_and_jump` code. This is the log that drove the RTC-overlap compatibility fix. |
| `kern_stateless_loader_final.txt` | **Final Kern stateless hand-off (emu).** Same loader with the Phase 22 compatibility patch; signed bundle platform `kern_esp32p4`; 6-segment Kern image. Shows `Platform accepted: kern_esp32p4`, `Signature verification PASSED!`, `Image OK: 6 segments`, `JMP[1..7]`, `[KERN-SHIM] __wrap_call_start_cpu0`, `app_main()`, `wave_43: ESP32-C6 held in reset`, `esp_lvgl:adapter: LVGL adapter initialized successfully`, and `wave_43: MIPI DSI PHY Powered on`. Captured with `--exit-on "MIPI DSI PHY Powered on"`; no further claim past the absent panel. Includes the loader's RTC-overlap skip warning for segment 5 (`0x50108080-0x501080A4`). |
| `kern_hw_virtual_efuse_firstboot.txt` | **Physical P4 rev 1.3, first loader boot (virtual-eFuse bring-up).** IDF 5.5 loader flashed with `CONFIG_EFUSE_VIRTUAL=y`; the 2nd-stage bootloader simulates the SB V2 key burn. Shows `secure_boot_v2: Burning public key hash to eFuse` and `efuse: Virtual efuses enabled: Not really burning eFuses`, then the loader mounts SD and loads the then-present legacy `seedsigner_esp32p4.bin` (194,864 bytes). The capture ends partway through that first boot's anti-phishing fill; the next boot verifies the stored hash and boots the Kern bundle. No physical eFuse write; no `espefuse.py`/provisioning command. |
| `kern_stateless_loader_hw.txt` | **Physical Kern stateless hand-off.** Board ESP32-P4 rev v1.3, MAC `e8:f6:0a:e0:ec:44`. Same virtual-eFuse loader; SD bundle uploaded in place with the RAM-only `uploader/` (`tools/sd_upload.py`) while stored under the `seedsigner_esp32p4.bin` filename, internal platform `kern_esp32p4`. Shows `eFuse virtual mode is enabled ... FOR TESTING ONLY!`, `secure boot v2 is already enabled, continuing..`, `Platform accepted: kern_esp32p4`, `Signature verification PASSED!`, anti-phish proof `wonder echo bomb balcony`, `Image OK: 6 segments, entry=0x4FF01F90`, `JMP[1..7]`, `[KERN-SHIM] __wrap_call_start_cpu0`, `app_main()`, C6 reset, LVGL adapter, and `MIPI DSI PHY Powered on`. |
| `specter_emu_stateless_boot.txt` | **Specter-DIY stateless hand-off (emu), first boot.** sandman `f54e345` MicroPython payload (3,480,992 B) signed as `specter_esp32p4`; virtual-eFuse SB V2 first burn (`Not really burning eFuses`). Shows `Platform accepted: specter_esp32p4`, `Signature verification PASSED!`, `Image OK: 8 segments, entry=0x4FF05382`, JMP[1..7], `__wrap_call_start_cpu0`, 16.25 MB PSRAM heap, REPL RX ISR, and the frozen `main.py` running (the two `pyb:` stub lines), then the app stalls in display init. The emu overlay skips the anti-phishing fill for speed. |
| `specter_emu_gdb_boot.txt` | Same Specter boot with `--gdb 1234 --elf build-W43/micropython.elf`; the boot log for the GDB evidence run. |
| `specter_emu_gdb_bt.txt` | **GDB backtrace at the Specter stall.** Frames `esp_lcd_new_dsi_bus` (`esp_lcd_mipi_dsi_bus.c:98`, the `mipi_dsi_phy_ll_is_pll_locked` wait) <- `p4board_display_init` <- `tft_init` <- `display_init` <- `mp_execute_bytecode` <- `pyexec_frozen_module("main.py")` <- `mp_task`. This is the absent-panel blocker, not a loader/shim failure. |
| `specter_hw_stateless_boot.txt` | **Physical P4 rev 1.3 Specter stateless SD boot (clean payload).** Rebuilt loader (`976ee3a` + `kern-image-compat.patch` only, no emu overlay, virtual eFuses), flashed `0x2000`/`0x20000`/`0x30000`; bundle uploaded to the card over UART with the RAM-only `sd_upload.py`. Shows `[Virtual] Loading virtual efuse blocks from flash: 0x28000`, SD mount -> TOCTOU-safe unmount -> `Loaded 3481584 bytes from /sdcard/specter_esp32p4.bin`, `Platform accepted: specter_esp32p4`, `Signature verification PASSED!`, anti-phish `wonder echo bomb balcony` (reused from the Kern fill via the NVS magic), `Image OK: 8 segments, entry=0x4FF05382`, `JMP[1..7]`, shim heap 16,250,496 B, REPL RX ISR, frozen `main.py` pyb stubs. Captured with `Phase_22/tools/capture_serial.py` (`idf.py monitor` needs a TTY). |
| `specter_hw_display_diag.txt` | Clean payload + only the Python `[P22-DIAG]` prints (`hw-diag-main-prints.patch`). Boot ends at `main: calling display.init` - display init never returns within the capture window (same as emu, at the Python level). |
| `specter_hw_display_diag2.txt` | Same, plus the C-level `ESP_LOGE` step markers (`hw-diag-display-markers.patch`). Silicon reaches `dsi bus ok` -> `dbi io ok` -> `dpi panel ok` -> `callbacks ok` -> `reset_lcd ok`, then blocks inside `send_st7701_init()`. Proves the emulator's DSI PLL stall is **not** reproduced on real silicon. |
| `specter_hw_display_skip_diag.txt` | Same diagnostics, with `send_st7701_init()` short-circuited. `display.init` returns, `sdram mounted`, `starting Specter GUI`; then `E lcd.dsi: ... underrun` + `[Errno 19] ENODEV` (printed by `Specter.handle_exception`) and an app-level `SW_CPU_RESET` loop. Several boot cycles captured. |
| `specter_hw_gui_diag.txt` | Same as above plus the try/except probe around `Specter.start()`. Confirms the ENODEV never propagates out of `start()` - the app handles it internally - and the reset follows the app's error path. |

Reproduce the baseline with `Phase_22/tools/build_kern_emu.sh` (Kern build + merge + rev-1.3 emu route).

Reproduce the stateless hand-off with:

```sh
RUN_EMU=1 ./Phase_22/tools/build_kern_stateless_emu.sh
```

The stateless script builds a **clean** Kern `7cdd258` and loader `976ee3a` in the gitignored `Phase_22/build/kern-work`, applies the Phase 21 emulator-only flash-injection overlay and the Phase 22 Kern compatibility patch, signs the payload as `kern_esp32p4`, merges, and boots the rev-1.3 route. The bundle is injected into the emulator's raw flash because esp-emu has no SD card; it is **not** placed in an app partition.

On hardware the same bundle is read from SD. The physical loader build (IDF 5.5, `CONFIG_EFUSE_VIRTUAL=y` + `KEEP_IN_FLASH=y`, EMU overlay not enabled) is flashed to `0x2000`/`0x20000`/`0x30000` with the Kern stateless ptable at `0x10000` and `ota_data_initial.bin` at `0x1e000`; the bundle goes to the card via the loader's RAM-only uploader (`uploader/`, `tools/sd_upload.py`, `esptool load_ram` - no card ejection, no flash/eFuse writes). See `kern_stateless_loader_hw.txt`.

No physical eFuse was written. The `--efuse` blob is generated by `Phase_21/tools/make-efuse.py`, and `CONFIG_EFUSE_VIRTUAL=y` keeps eFuse reads/writes virtual. The final run's NVS uses the payload-local flash partition; this is accepted persistent application data, not an executable flash payload.

## Specter (Track B)

```sh
RUN_EMU=0 ./Phase_22/tools/build_specter_stateless_emu.sh   # build + sign + merge
EMU_GDB=1 RUN_EMU=1 ./Phase_22/tools/build_specter_stateless_emu.sh   # boot with GDB stub
```

The script rebuilds clean sandman `f54e345` + MicroPython `8cf130db34` + loader `976ee3a` in the gitignored `Phase_22/build/specter-work`, applies the `Phase_22/specter_changes/` overlay (shim component, stateless sdkconfig/partition table, MicroPython patches), signs the 3.48 MB MicroPython image as `specter_esp32p4`, injects the bundle at emulator flash `0x13FF00`, and boots the rev-1.3 route. The bundle is never placed in an app partition.

At the app stall (after the two `pyb:` stub lines), attach GDB in a second shell:

```sh
. ~/esp/esp-idf-v5.5/export.sh
riscv32-esp-elf-gdb -ex 'target remote :1234' -ex bt \
  Phase_22/build/specter-work/build-W43/micropython.elf
```

The expected top frame is `esp_lcd_new_dsi_bus` at `esp_lcd_mipi_dsi_bus.c:98` (PHY PLL wait). See `specter_emu_gdb_bt.txt`.

Hardware (run Oct 20, 2026, physical P4 rev 1.3) uses the same bundle, but the loader is built **without** `EMU_FLASH_PAYLOAD=1`; the loader reads `/sdcard/specter_esp32p4.bin` (one of its accepted filenames), and the bundle is uploaded over UART with `tools/sd_upload.py` - no card ejection, no flash/eFuse writes. The old Kern bundle must be removed from the card first: it is stored as `seedsigner_esp32p4.bin`, which the loader probes before `specter_esp32p4.bin`. Capture headless with `Phase_22/tools/capture_serial.py --reset --seconds N -o <log>` (plain pyserial; `idf.py monitor` refuses to run without a TTY). Result: `specter_hw_stateless_boot.txt`; the diagnostic follow-ups pin the silicon display boundary and are indexed above.
