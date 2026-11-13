# Phase 21 Emulation Execution Logs

This directory contains raw UART telemetry captured from headless emulation runs using `esp-emu` (v0.49.0 for initial baselines, v0.50.0 for final MMU-fixed runs). Merged firmware images were generated and executed via [tools/run_emu.sh](../tools/run_emu.sh).

## Log Catalog

| Log File | Target & Setup | Verification Property Proven |
|---|---|---|
| `s3_sd_halt.txt` | ESP32-S3 faithful build (Secure Boot V2 enabled, `REV_MIN_0`) | Secure Boot V2 first-burn runs in emu; loader halts fail-closed when SD card is absent (`SDMMC mount failed (ESP_ERR_TIMEOUT)` -> `Failed to mount SD card. Halting.`). |
| `s3_hello_e2e.txt` | ESP32-S3 + `EMU_FLASH_PAYLOAD` overlay + signed hello shim | Full stateless boot chain: Secure Boot -> bundle verification passed -> 5.875 MB flash fill and hash -> BIP-39 words `arctic melody humor slow` (deterministic across 8 cycles) -> Cache MMU remap -> `Hello world!` execution. |
| `s3_mp_repl.txt` | ESP32-S3 + `EMU_FLASH_PAYLOAD` overlay + MicroPython v1.27.0 | Stateless boot to interactive MicroPython REPL (banner + `>>>`). Words `cruel push unusual adapt` differ from hello bundle as designed. Injected CR-terminated commands evaluate cleanly (`print('emu21-repl-ok')`, `sys.platform`). |
| `p4_sd_halt.txt` | ESP32-P4 faithful build with `emu_rev_p4.defaults` (rev 3.1 + Secure Boot V2 enabled) | Layer 1 Secure Boot V2 RSA-PSS digest generation and virtual eFuse burn succeeds; loader boots into `app_main` and halts fail-closed on absent SD card (`Failed to mount SD card (ESP_ERR_TIMEOUT)`). |
| `p4_hello_e2e.txt` | ESP32-P4 with `emu_rev_p4.defaults` + overlay + signed hello shim | Secure Boot V2 verification, bundle signature verification passed, and TRNG `random_fill` flash fill initiated. |
| `p4_hello_boot_e2e.txt` | ESP32-P4 with fast-skip overlay + rev-3.1 matched hello shim | Full stateless boot on P4: loader plan -> `JMP[1..7]` -> payload `cpu_start` -> `Hello world!` across 46 consecutive reboot cycles in a single session. |
| `p4_mp_e2e.txt` | ESP32-P4 rev-3.1 model + MicroPython rev-3.1 rebuild | Instruction fetch at `0x4FF447BE` returns zeros on the rev-3.1 model, leading to `Illegal instruction`. Resolved via rev-1.3 route. |
| `p4_rev13_hello_abort.txt` | ESP32-P4 rev-1.3 route, pre-fix loader | Demonstrates loader regression E8: `call_start_cpu0` payload aborts due to missing 32-byte image-header staging. |
| `p4_rev13_hello_boot_e2e.txt` | ESP32-P4 rev-1.3 route + header staging patch | Verifies that restoring 32-byte header staging allows hello payload to boot cleanly through `call_start_cpu0`. |
| `p4_rev13_hello_upstream_e2e.txt` | ESP32-P4 rev-1.3 route on unpatched upstream loader (`0361736`) | Confirms the header staging fix landed upstream in the bootloader mainline; boots hello payload across 237 cycles without local patches. |
| `p4_rev13_mp_repl_boot.txt` | ESP32-P4 rev-1.3 route + stock pre-v3 MicroPython | Full headless boot of stock pre-v3 MicroPython image to banner and `>>>` prompt. |
| `p4_rev13_mp_repl_input.txt` | ESP32-P4 rev-1.3 route + stock pre-v3 MicroPython with input injection | Evaluates injected CR-terminated REPL input: `P4MP-REPL-OK 4` and `IMPL micropython`. |
| `p4_rev13_hello_mmu_fixed_e2e.txt` | ESP32-P4 rev-1.3 route on esp-emu v0.50.0 without identity-copy workaround | Proves upstream fix for [esp-emulator#24](https://github.com/espressif/esp-emulator/issues/24): production S-MMU remap (`0xC04`/`0xC05`) is honored by emulator translation; boots hello payload across 230 cycles in 240 seconds. |
| `p4_rev13_mp_mmu_fixed_e2e.txt` | ESP32-P4 rev-1.3 route on esp-emu v0.50.0 + stock pre-v3 MicroPython | Full MicroPython boot to `>>>` and command execution with zero identity-copy workarounds, confirming dynamic PSRAM remapping matches silicon semantics. |

## Notes on Artifacts

- **JMP Entry Readback:** The debug log print `JMP[5] entry bytes` is an unmapped internal SRAM inspection artifact and does not represent the actual entry code fetch; execution verifies correctness.
- **Identity-Copy Workaround Retired:** The `JMP[6.5]` identity copy was a temporary workaround for esp-emu <= 0.49.0 flat translation. Following the upstream fix in esp-emu v0.50.0 ([esp-emulator#24](https://github.com/espressif/esp-emulator/issues/24)), the workaround was removed.
- **ADC Calibration Warning:** A 64-line burst of `eFuse: calibration efuse version does not match` occurs during MicroPython C++ constructor initialization because the synthetic `--efuse` blob omits factory calibration data. On physical silicon, ADC calibration is populated by Espressif factory fuses; in emulation this warning is harmless.
