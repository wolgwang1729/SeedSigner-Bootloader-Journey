# Phase 22: Cross-Project Bring-Up - Kern and Specter-DIY

- **Date:** October 19, 2026 (Updated October 20, 2026)
- **Author:** Mayank (wolgwang)
- **Project:** SeedSigner Secure Boot — Independent Continuation
- **Status:** Complete - Closed October 20, 2026 on physical ESP32-P4 rev 1.3 silicon and esp-emu. Zero physical eFuse burns.
- **Hardware:** ESP32-P4-WIFI6-DEV-KIT headless (v1.3 silicon, 16 MB flash) + esp-emu v0.50.0.
- **Scope Notice:** Proves universal stateless bootloader compatibility across independent Bitcoin hardware wallet firmwares (Kern and Specter-DIY) without physical display modules or irreversible eFuse modifications.

---

## 1. Overview & Motivation

Phases 23-27 are gated on panels, spare burn silicon, or both. Neither exists right now. Phase 22 is the next track that needs **neither**:

- It runs on the P4 dev board already on the desk.
- It uses the loader's existing Layer 1 (Secure Boot V2, virtual eFuses) + Layer 2 (Specter secp256k1 multisig) chain unchanged.
- It answers the loader's actual product question: *is this a SeedSigner-only loader or a reusable security layer?* The project claims SeedSigner, Specter and Kern; this phase tests that claim with code instead of prose.

Kern is first because it is already an ESP32-P4, C, ESP-IDF v6.1 firmware with `CONFIG_SPIRAM_XIP_FROM_PSRAM=y` and the same pre-v3 silicon selection as the dev board. Specter-DIY is second because it is the origin of the loader's bundle format, and an ESP32-P4 port is being worked upstream (Phase 0 notes: Mike Tolkachev was porting Specter-DIY and its bootloader to Waveshare P4 boards).

**No display/camera claims.** Kern and Specter both expect an LCD (and Kern a MIPI-CSI camera) for their normal UI. With no panel attached, the milestone is an **app-level UART milestone** (entry reached, init logged, specific failure point identified), not a working wallet UI. That is the same headless-slice honesty rule as Phase 19.

---

## 2. Track A - Kern (`odudex/Kern`)

**Target:** `wave_43` (480×800 MIPI DSI, GT911, OV5647) because the repo's P4 firmware target is `WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43`; the physical board is the headless DEV-KIT, so only the boot path is in scope.

### A1. Build the unmodified reference
- `git clone --recursive https://github.com/odudex/Kern.git`
- Build with ESP-IDF **v6.1** (side-by-side install from Phase 21), `wave_43`, pre-v3 silicon:
  - `just build wave_43` (uses `sdkconfig.defaults` + `sdkconfig.defaults.wave_43`, which select `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y`)
  - or `idf.py -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.defaults.wave_43' build`
- Record: `kern.bin` size, `idf.py size`, flash/PSRAM segment table, entry symbol, secure-boot signing settings, partition table.
- Baseline flash + UART log on the dev board (normal bootloader, no stateless loader) to learn exactly where it stops without a panel. This is the control we must reproduce or explain.

### A2. Audit the image against the loader's P4 mapping
- Kern already links IROM/DROM into PSRAM (`CONFIG_SPIRAM_XIP_FROM_PSRAM=y`), which is the layout the Phase 12/13 loader expects.
- Verify every segment's load address against the loader's routing:
  - `0x48000000-0x4C000000` -> MMU-mapped from PSRAM
  - internal SRAM / L2MEM -> direct copy
  - RTC / other regions -> explicit handling or fail-closed
- Check the image header/entry (`call_start_cpu0` vs shim path), segment count, and whether any segment falls outside the loader's `MAX_FIRMWARE_SIZE` (8 MB) or mapping assumptions.
- Check the ESP-IDF v6.1 image format against the v5.5 loader parser (`main/esp_image.c`); document any field/layout drift.

### A3. Stateless handoff
- Start with the reusable `stateless_shim` (Phase 11/12): `__wrap_call_start_cpu0` + CLIC vector-table install (`esp_cpu_intr_set_ivt_addr`, `esp_cpu_intr_set_xtvt_addr`) + `.data` ownership.
- If Kern needs the stock `call_start_cpu0` path instead, use the Phase 12 stock-shim recipe and verify the 32-byte image-header staging fix (`0361736`) is present in the loader checkout.
- Keep the handoff change in a scratch/Phase 22 copy or a documented loader patch - do not silently fork the production loader.

### A4. Bundle and platform binding
- Extend the signing tool (or add a Phase 22 variant) to accept the platform string and key slot rather than hardcoding `seedsigner_esp32p4` and the dummy key. Proposed values: `kern_esp32p4`, `specter_esp32p4`.
  - **Executed:** platform string, accepted-platform table and per-platform SD filenames landed (`kern-image-compat.patch`). Per-platform **key slots** were deliberately deferred - the phase tests cross-project execution, not key separation; see §10.1.5.
- Decide the loader-side policy: a small accepted-platform table (recommended for a multi-project loader) vs one loader build per project. Record the choice and the key-table implications.
- Wrap `kern.bin` into `seedsigner_esp32p4.bin`-format bundle (rename only at the SD-card path, or add a `kern_esp32p4.bin` path to the loader).
- Copy to a FAT32 SD card and boot.

### A5. Flash-state assumptions (the likely blocker)
Kern is stateful by design: NVS (settings/PIN), `otadata`, OTA slots, and a SPIFFS `storage` partition. Options, in order of preference:
1. **Tolerate empty state:** run with a blank NVS and let Kern initialize defaults; prove what it does when `otadata`/`storage` are absent.
2. **Stub/redirect:** add a Phase 22 shim that answers NVS/OTA/SPIFFS calls from RAM or the SD card (dev-only, documented).
3. **Document the blocker:** if Kern cannot reach `app_main` without its data partitions, record the exact call site and make that the phase's Kern result - a negative result is still a loader-boundary finding.

**Decision (Oct 19):** persistent NVS is **allowed**. It is application data (settings/PIN), not executable code; the stateless guarantee is that the signed payload never becomes a flash-resident app partition, not that the application performs zero flash writes. The payload keeps a local `nvs` partition and a narrow `esp_ota_get_running_partition()` wrapper for IDF's PSRAM-XIP safety check (see §10). No RAM-backed NVS is required.

### A6. Kern acceptance evidence
- UART log: Secure Boot V2 lines -> Specter header/multisig PASSED -> platform accepted -> JMP -> Kern entry.
- One of:
  - `app_main` reached + Kern banner/init logs, or
  - a documented, reproducible blocker (e.g., `nvs_flash_init` / `esp_vfs_spiffs_register` / display init) with the call site and the loader state that caused it.
- No flash payload, no eFuse burns.

---

## 3. Track B - Specter-DIY

**Target:** Specter-DIY on ESP32-P4, MicroPython, booted from a signed SD bundle through the same loader.

**Result (Oct 20, 2026):** proven in esp-emu **and on the physical P4 rev 1.3** - signed `specter_esp32p4` bundle -> SB V2 (virtual eFuses) -> secp256k1 multisig PASSED -> JMP -> MicroPython shim -> frozen Specter `main.py`. In emu the app stalls at `esp_lcd_new_dsi_bus` (absent panel); on silicon the DSI PHY PLL locks and the stock payload blocks in `send_st7701_init()`, with the post-skip app error path documented in §11.5. See §11 for the build, image contract, evidence and compatibility findings.

### B1. Source the P4 port
- Preferred: Mike Tolkachev's upstream ESP32-P4 port (referenced in `Phase_0_Stakeholder_Alignment.md`). Ask for the branch/status; if it is not public, record that and fall back.
- Fallback: build Specter's Python app on the Phase 18 P4 MicroPython builder, which already carries `esp-secp256k1`, LVGL 9.5, and the stateless shim. Specter needs its native `secp256k1` module and LVGL bindings; both exist in the builder's dependency set.
- Do **not** try to run the STM32F469 `disco` build on P4 - architecture and board drivers differ.

### B2. Build and freeze the app
- Freeze the Specter Python package into the P4 MicroPython image (or stage it on SD as `.py`/`.mpy` if the image stays smaller).
- Keep the MicroPython base pinned to the same clean upstream revision used by the existing P4 payload; all Specter changes travel as a patch/overlay, not as a dirty submodule.
- Record image size, frozen module list, native modules, and RAM/heap at boot.

### B3. Bundle and boot
- Sign with platform `specter_esp32p4` and its own key slot (see A4).
- Boot on P4 through SB V2 -> Specter multisig -> JMP -> MicroPython -> Specter app entry.
- Headless milestone options (pick the furthest reachable):
  1. MicroPython REPL + `import specter` succeeds,
  2. Specter app entry / controller init runs and logs over UART,
  3. UI init fails only at the display/camera driver (documented, expected without panels).
- Measure boot time to the milestone and compare with the plain MicroPython payload.

### B4. Bundle-format drift check
- Compare the loader's `specter_crypto` section format, platform attribute, `pl_ver`, and signature message with current upstream `specter-bootloader`.
- Document any divergence (the loader was ported in Phase 9/12 and may lag upstream). No silent format changes: if the loader must change, add a regression test.

### B5. Specter acceptance evidence
- UART log: SB V2 -> Specter multisig PASSED -> platform accepted -> JMP -> MicroPython banner -> documented Specter milestone.
- Same no-flash-payload, zero-burn rules as Track A.

---

## 4. Acceptance matrix

| Check | Kern | Specter |
|---|---|---|
| Built for P4 pre-v3 | `wave_43` / IDF v6.1 | sandman `f54e345` / MicroPython `8cf130db34` / IDF 5.5, `REV_LESS_V3=y` |
| Image segments fit loader mapping | 6 segments, 1.94 MB (§10.1) | 8 segments, 3.48 MB, entry `0x4FF05382` (§11.1) |
| Signed bundle (new platform string) | `kern_esp32p4` | `specter_esp32p4` |
| SB V2 verification | PASSED (virtual-eFuse route) | PASSED (virtual-eFuse route) |
| Specter secp256k1 multisig | PASSED | PASSED |
| JMP + PSRAM execution | `JMP[1..7]` + shim + `app_main` | `JMP[1..7]` + shim + MicroPython entry |
| App-level milestone over UART | `app_main` / LVGL adapter / MIPI DSI PHY (§10.2) | frozen `main.py` running; display blocker documented (GDB) |
| No flash payload | emu flash injection only; hardware SD | emu flash injection only |
| Zero eFuse burns | virtual eFuse only | virtual eFuse only |
| Display/camera UI | **not claimed** | **not claimed** |
| Mainnet / production support | **not claimed** | **not claimed** |

**Phase closes when both rows have a UART log and the write-up states exactly what was and was not proven.** A failed track with a precise blocker still counts as a result; a "looks like it boots" without a log does not.

**Closed Oct 20, 2026** - both rows satisfied on emu and on the physical P4 rev 1.3. Per-platform key slots are a follow-up isolation hardening item (§10.1.5), not part of this phase's goal, which was proving the loader runs all three stacks.

---

## 5. Risks / unknowns

| Risk | Mitigation |
|---|---|
| Kern display init aborts before `app_main` | Capture the control boot first; if it aborts in LCD/DSI init, document the call site and treat boot-to-entry as the milestone. |
| Kern needs NVS/OTA/SPIFFS partitions | A5 options 1-3; prefer tolerate-empty-state, then a documented dev shim. |
| Kern v6.1 image layout differs from the v5.5 loader parser | A2 audit; add parser compatibility only behind a tested branch. |
| Kern binary exceeds the loader's 8 MB cap | Check `idf.py size`; strip unused camera/IPA/LVGL demo code or reject the target and document. |
| Specter P4 port not available upstream | Fall back to the Phase 18 builder; scope Track B to import/entry if the app's board layer is too large to port. |
| Specter native modules missing for P4 | Reuse `esp-secp256k1`; LVGL already builds for P4; document any missing module as a blocker. |
| Two platforms in one loader weakens the trust story | Per-platform key slots + explicit accepted-platform table; never accept a bundle under another project's key. Explicit table landed; per-platform key slots deferred as a follow-up isolation item (§10.1.5). |
| Headless runs get mistaken for product proof | Every log/status line says "headless, no LCD/CSI claim"; Phase 22 is a bring-up proof only. |

---

## 6. Non-goals

- No LCD/camera/QR workflow, no on-screen anti-phishing words.
- No mainnet use, no production support promise for Kern or Specter.
- No eFuse burns, no flash-encryption provisioning, no secure-boot eFuse writes.
- No rewrite of the production loader's verification path. New platform policy is additive and tested.
- No upstream PRs required to close the phase (filing them is a bonus; the proof lives here).

---

## 7. Deliverables

| Path | Contents |
|---|---|
| `Phase_22/Phase_22_Kern_Specter_Bringup.md` | this write-up + results/log index |
| `Phase_22/tools/` | build/sign helpers, platform-aware bundle wrapper, segment-table checker |
| `Phase_22/loader_changes/` | platform-policy / handoff patches (only if the mainline must change) |
| `Phase_22/logs/` | Kern control + stateless UART logs, Specter control + stateless UART logs |
| `Phase_22/build/` | gitignored workspace: source clones (`Kern/`, `specter-p4/`, `micropython/`), work trees (`specter-work/`, `kern-work/`), signed `kern_esp32p4.bin` / `specter_esp32p4.bin`, `emu_specter.bin`, `efuse_p4_rev1.3.bin`, and the flashed hardware loader in `hw-loader/` (no private keys) |

---

## 8. Open questions (answer while executing)

1. Does Kern reach `app_main` with no display attached and blank NVS, or does it abort in board init? (Control boot first.)
2. Does Kern's v6.1 app image parse cleanly with the v5.5 loader, or is a compatibility shim needed?
3. Is Mike's Specter P4 port available, and which MicroPython revision/board target does it use?
4. Should the loader accept multiple platforms in one build, or should each project get its own loader build? (Recommendation: one build, per-platform key slots, explicit table - but prove it on both.)
5. How much of Specter's app can run before its display/camera layer is needed?

**Answers (Oct 19-20, 2026):**

1. Kern reaches `app_main()` with a blank payload-local NVS; the only extra shim is IDF's PSRAM-XIP `esp_ota_get_running_partition()` lookup (§10.1.3).
2. Kern's IDF 6.1 secure-signed image needed the zero-address padding-segment skip; the final stateless build is unsigned at the IDF layer and parses as 6 segments (§10.1.1).
3. `sandman21vs/specter-diy` branch `esp32-p4-port` (`f54e345`) was public and sufficient; Mike's branch status was not needed. It is an unaudited PoC (§11).
4. One loader build with the explicit accepted-platform table works for both projects; per-platform key slots remain a follow-up isolation item (§10.1.5), not a Phase 22 gate - this phase tests cross-project execution, not key separation.
5. All frozen imports and Specter's `platform` module init run; `main()` stops at `display.init()` -> `esp_lcd_new_dsi_bus()` (PHY PLL wait, absent panel). Nothing past display init is exercised (§11).

---

## 9. First result - Kern baseline in esp-emu (Oct 19, 2026)

**Build:** `Phase_22/tools/build_kern_emu.sh` - Kern `7cdd258`, ESP-IDF **v6.1**, `wave_43` (pre-v3), overlay `sdkconfig.defaults.emu` with `CONFIG_EFUSE_VIRTUAL=y` + `CONFIG_EFUSE_VIRTUAL_LOG_ALL_WRITES=y` (no `KEEP_IN_FLASH`, no `efuse` partition, no physical burn).

**Merged image:** 2.1 MB - bootloader `@0x2000`, partition table `@0x10000`, `ota_data_initial @0x1e000`, `kern.bin @0x20000` (signed app, 8 segments, ~1.98 MB).

**Run:**
```sh
esp-emu --chip esp32p4 --firmware Phase_22/build/Kern/build_wave_43_emu/kern_emu.bin \
  --psram-size 32M \
  --rom ~/.espressif/tools/esp-rom-elfs/20241011/esp32p4_rev0_rom.elf \
  --efuse Phase_22/build/kern_efuse_p4_rev1.3.bin --timeout 180s
```

**Result** (`logs/kern_emu_first_boot.txt`):

- `ESP-IDF v6.1 2nd stage bootloader`, `chip revision: v1.3`, `eFuse virtual mode is enabled` - the intended IDF/rev/eFuse combination.
- The app image parses and boots: `.text`/`.rodata` mapped into PSRAM XIP (`vaddr=0x48170020` / `0x48000020`), DIRAM/RTC segments loaded, `main_task: Calling app_main()`.
- Kern app init runs: `wave_43: ESP32-C6 held in reset` -> `esp_lvgl:adapter: LVGL adapter initialized successfully` -> `wave_43: MIPI DSI PHY Powered on`.
- No further UART output before the 180 s timeout.

**Interpretation:** the unmodified Kern image boots through the real ROM + 2nd-stage bootloader + IDF startup + `app_main()` in emu. The first absent-hardware blocker is the MIPI DSI panel bring-up (`esp-emu` models no DSI panel), exactly the predicted headless failure. This is a baseline only - no stateless loader, no SD bundle, no display claim.

**Next:** (a) add a dev-only headless display shim in a scratch Kern copy to see how far `app_main()` gets past `bsp_display_start()`; (b) do the A2 segment-table audit and wrap `kern.bin` in a signed bundle for the loader. Both were superseded by the stateless hand-off in §10.

---

## 10. Second result - Kern stateless hand-off (emu + hardware, Oct 19, 2026)

**Build:** clean Kern `7cdd258` + `Phase_22/kern_changes/kern-stateless.patch`, ESP-IDF **v6.1**, `wave_43` (pre-v3), overlay `sdkconfig.defaults.stateless`:
`CONFIG_FREERTOS_UNICORE=y`, `CONFIG_ESP_SYSTEM_SINGLE_CORE_MODE=y`, `CONFIG_EFUSE_VIRTUAL=y`, `CONFIG_SPIRAM_MEMTEST=n`, and IDF's secure-boot app check disabled (`CONFIG_SECURE_BOOT=n`, `CONFIG_SECURE_SIGNED_APPS_NO_SECURE_BOOT=n`, `CONFIG_SECURE_SIGNED_ON_UPDATE_NO_SECURE_BOOT=n`). The loader's Layer 2 bundle verification is authoritative for this payload.

**Kern image:** 1,936,864 bytes, **6 segments**, entry `0x4FF01F90`. Segments: DROM/IROM `0x48170020`, TCM `0x30100000`, DIRAM `0x4FF00000`, DROM/IROM `0x48000020`, DIRAM `0x4FF064B0`, RTC `0x50108080` (36 bytes). The 36-byte RTC segment is sleep-mode state (`.rtc.force_slow`), not boot-critical.

**Payload-local partition table** (`kern_changes/partitions_stateless.csv`, at `0x10000`; the loader keeps its own table at `0x20000`): `nvs @ 0x11000` (28 KB), `otadata @ 0x1E000` (8 KB), and a metadata-only `factory @ 0x30000` (2 MB) entry. The factory entry is never booted or written; it only gives IDF's partition-safety code a non-NULL app range.

**Loader:** clean `976ee3a` + Phase 21 `EMU_FLASH_PAYLOAD` overlay + `Phase_22/loader_changes/kern-image-compat.patch`, ESP-IDF v5.5. The bundle is signed as **`kern_esp32p4`** with the test profile and injected as a Specter bundle at emulator flash `0x13FF00` (the ESP image starts at `0x140000`). It is **not** placed in an app partition. On hardware the same bundle is read from SD (`kern_esp32p4.bin` is one of the accepted filenames).

**Result** (`logs/kern_stateless_loader_final.txt`):

- `Platform accepted: kern_esp32p4` - the additive accepted-platform table accepts SeedSigner P4/S3 plus Kern/Specter P4 strings; the signer's `choices` list matches.
- `Specter bootloader section detected` -> `Signature verification PASSED!` -> `Image OK: 6 segments, entry=0x4FF01F90`.
- `JMP[1..7]` enters the loader's cache-off RTC trampoline, remaps IROM/DROM to PSRAM, and jumps.
- `[KERN-SHIM] __wrap_call_start_cpu0 entered` -> IDF v6.1 stage 0 / constructors / stage 1 -> `[KERN-SHIM] jumping to esp_startup_start_app`.
- `main_task: Calling app_main()` -> `wave_43: ESP32-C6 held in reset` -> `esp_lvgl:adapter: LVGL adapter initialized successfully` -> `wave_43: MIPI DSI PHY Powered on`.
- Captured with `--exit-on "MIPI DSI PHY Powered on"`; no abort and no further claim past the absent DSI panel.

This is a **full stateless-loader hand-off into a foreign ESP-IDF 6.1 application**, headless and burn-free. It is stronger than the minimum Kern milestone (`app_main` + init logs) and stops at the same absent-panel boundary as the baseline.

### 10.1 Compatibility findings

1. **IDF 6.x zero-address padding segment.** The secure-signed Kern image had **8 segments**, including a zero-address padding segment before the image signature block; the v5.5 loader parser rejected it as outside the P4 memory windows. `kern-image-compat.patch` skips zero-address segments in both parser passes and advances `offset` by `seg.data_len` (the second-pass `continue` must advance the offset, or the next header is read 36 bytes early). The final stateless build disables secure app signing and has 6 segments, but the compatibility path remains for other IDF 6.x images. The first 8-segment attempt is preserved in `logs/kern_stateless_loader_emu.txt` (it failed earlier, at the RTC overlap).

2. **Loader RTC/JMP overlap.** The loader's cache-off `do_mmu_mapping_and_jump` lives in `.rtc.text` at `0x50108080-0x50108600`; Kern's RTC segment starts at the same address with 36 bytes of sleep state. A direct copy overwrote the code that was executing the copy, producing `Illegal instruction ... PC=0x50108080`. The patch detects overlap with `_rtc_text_start.._rtc_text_end` **before** the direct-copy/`MAX_DIRECT_COPIES` accounting, logs a warning, skips the segment, and advances the parser offset. This is a documented loader policy: a payload that truly needs RTC state across the stateless hand-off must be rejected, not silently truncated. The final log shows the skip for segment 5 (`0x50108080-0x501080A4`).

3. **`esp_ota_get_running_partition()` cannot describe PSRAM XIP.** After NVS init began, IDF's `esp_partition_main_flash_region_safe()` called `esp_ota_get_running_partition()`, which uses `spi_flash_cache2phys()`/an app-partition lookup and aborted because the app is executing from PSRAM, not a flash app partition. `kern_changes/main/stateless_ota.c` is an explicit dev shim: it links with `-Wl,--wrap=esp_ota_get_running_partition` under `CONFIG_KERN_STATELESS` and returns the payload-local metadata app partition. This is why the stateless ptable carries the metadata-only `factory` entry; no code is loaded from `0x30000` by the payload.

4. **Persistent NVS/SPIFFS state is accepted application data.** NVS initialization runs against the payload-local `nvs` partition at `0x11000` (and `otadata` at `0x1E000`). This is intentional: the stateless guarantee is about executable code (the signed bundle is never installed as a flash app partition), not about a zero-write application. Kern's settings/PIN persistence is normal wallet behavior. The only shim required is IDF's PSRAM-XIP OTA lookup (item 3); `stateless_ota.c` returns the metadata partition so NVS write-safety checks pass. SPIFFS was not exercised because the run stops at the absent panel, but it is the same class of persistent app data.

5. **Key slots are still shared (known limitation, not a gate).** Platform strings are now checked per bundle, and the SD loader tries `seedsigner_esp32p4.bin`, `kern_esp32p4.bin`, and `specter_esp32p4.bin`, but the bundle is still verified with the shared `test` profile key. Per-platform key slots are the next isolation hardening item; do not treat the platform string alone as project isolation. This is deliberately out of Phase 22's goal (cross-project execution) and tracked as follow-up.

### 10.2 Physical P4 run (Oct 19, 2026)

Board: **ESP32-P4 rev v1.3**, MAC `e8:f6:0a:e0:ec:44`, `/dev/ttyACM0`; no display or camera attached. The loader is the IDF 5.5 build from clean `976ee3a` + `kern-image-compat.patch`; the Phase 21 emulator overlay was present in the scratch tree but **not enabled** (`EMU_FLASH_PAYLOAD` unset). The generated app **and** bootloader configs both contain `CONFIG_EFUSE_VIRTUAL=y` + `CONFIG_EFUSE_VIRTUAL_KEEP_IN_FLASH=y`; `CONFIG_SECURE_FLASH_ENC_ENABLED` is off.

**Flash writes (all reversible):**

| Offset | Contents | Notes |
|---|---|---|
| `0x2000` | loader bootloader | SB V2 signed, virtual eFuse |
| `0x10000` | Kern stateless partition table | payload-local `nvs`/`otadata`/metadata app |
| `0x1e000` | Kern `ota_data_initial.bin` | blank OTA selector |
| `0x20000` | loader partition table | production P4 table |
| `0x30000` | loader application | `seedsigner_secure_loader.bin` |

The Kern executable is **not** in flash. The signed bundle was uploaded to the card over UART with the loader's RAM-only SD uploader (`uploader/`, `tools/sd_upload.py`, `esptool load_ram`): no card ejection, no flash writes and no eFuse calls from the uploader. It was stored as `seedsigner_esp32p4.bin` because that is the loader's first filename probe; the **internal** platform string is `kern_esp32p4`.

**Evidence** (`logs/kern_stateless_loader_hw.txt`):

- bootloader: `eFuse virtual mode is enabled ... FOR TESTING ONLY!` and `secure boot v2 is already enabled, continuing..`
- `Platform accepted: kern_esp32p4` -> `Signature verification PASSED!`
- anti-phishing proof: `wonder echo bomb balcony`
- `Image OK: 6 segments, entry=0x4FF01F90`; segment-5 RTC skip; `JMP[1..7]`
- `[KERN-SHIM] __wrap_call_start_cpu0 entered` -> `main_task: Calling app_main()`
- `wave_43: ESP32-C6 held in reset`, `esp_lvgl:adapter: LVGL adapter initialized successfully`, `wave_43: MIPI DSI PHY Powered on`
- `nvs_sec_provider: NVS Encryption - Registering HMAC-based scheme...`

The first loader boot (before the SD swap) is preserved as `logs/kern_hw_virtual_efuse_firstboot.txt`. It shows the simulated first-burn path: `secure_boot_v2: Burning public key hash to eFuse` followed by `efuse: Virtual efuses enabled: Not really burning eFuses`. The capture ends partway through that first boot's anti-phishing fill; the next boot verifies the stored hash and boots the Kern bundle. No `espefuse.py`, `idf.py efuse` or provisioning command was run. The final boot's bootloader reports secure boot already enabled in the virtual state and verifies the signed app normally.

**Hardware reproduction:** build the loader exactly as `build_kern_stateless_emu.sh` does but **without** `EMU_FLASH_PAYLOAD=1` (the Phase 21 overlay stays compiled out), then flash the table's offsets with `esptool.py --chip esp32p4` and push the signed bundle straight to the card over UART:

```sh
cd ../seedsigner-esp32-bootloader
. ~/esp/esp-idf-v5.5/export.sh
python3 tools/sd_upload.py --chip esp32p4 --port /dev/ttyACM0 \
  --uploader-bin uploader/build/esp32p4/seedsigner_sd_uploader.bin \
  upload --name seedsigner_esp32p4.bin <path>/kern_esp32p4.bin
```

The uploader is the loader's own `uploader/` RAM app (`esptool load_ram`); it writes only the removable card and resets into the flashed loader afterwards. The loader tries `seedsigner_esp32p4.bin` before `kern_esp32p4.bin`, hence the destination name; acceptance is decided by the bundle's internal `kern_esp32p4` platform string.

### 10.3 Kern acceptance status

| Check | Result |
|---|---|
| Built for P4 pre-v3 | Kern `7cdd258`, IDF v6.1, `wave_43` |
| Image fits loader mapping | 6 segments; 1.94 MB payload |
| Signed bundle, `kern_esp32p4` | `Signature verification PASSED!` |
| SB V2 | loader boots through virtual-eFuse SB V2 route |
| Specter secp256k1 multisig | PASSED |
| JMP + PSRAM execution | `JMP[1..7]`, shim, `app_main` |
| App-level UART milestone | `app_main`, C6 reset, LVGL adapter, MIPI DSI PHY |
| Physical P4 SD boot | `logs/kern_stateless_loader_hw.txt` |
| No flash app partition | emu overlay + hardware SD; Kern code never in flash |
| Zero physical eFuse burns | virtual eFuse only; first boot logged `Not really burning eFuses` |
| Persistent NVS/settings state | accepted app data (payload-local `nvs` at `0x11000`) |
| Strict no-flash-write app | not a goal; the stateless guarantee covers executable payloads |
| Display/camera UI, mainnet | not claimed |

**Reproduce:** `RUN_EMU=1 ./Phase_22/tools/build_kern_stateless_emu.sh`. The script builds clean Kern `7cdd258` and loader `976ee3a` trees in the gitignored `Phase_22/build/kern-work`, applies both patches, signs as `kern_esp32p4`, merges, generates the rev-1.3 virtual eFuse blob, and boots esp-emu. Use `RUN_EMU=0` to stop after merge.

**Next:** Track B Specter-DIY (done, §11). The OTA wrapper is retained as documented PSRAM-XIP support, not a blocker. Per-platform key slots remain a follow-up isolation item (§10.1.5).

## 11. Third result - Specter-DIY stateless hand-off (emu + physical P4 rev 1.3, Oct 20, 2026)

**Build:** `Phase_22/tools/build_specter_stateless_emu.sh` - clean `sandman21vs/specter-diy` branch `esp32-p4-port` pinned at **`f54e345`** (the public P4 PoC; upstream PR cryptoadvance/specter-diy#389 is closed, so this is an unaudited port) + `Phase_22/specter_changes/` overlay, MicroPython **`8cf130db34`** (`master`, v1.30.0-preview-4 era) + `micropython-stateless.patch`, ESP-IDF **5.5**, board target `WAVESHARE_P4_43` (pre-v3 silicon selection: `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y`).

**Overlay:** a `stateless_shim` IDF component at `ports/esp32p4/idf_components/stateless_shim/` (already in the port's `EXTRA_COMPONENT_DIRS`; wired into the board cmake only with `-DMICROPY_STATELESS=1`). It keeps the Phase 18 mechanics - custom entry `my_entry_point`, `__wrap_call_start_cpu0`, the early-boot/cache/PSRAM/ROM-UART wrap set, OTA lookups returning NULL/`ESP_ERR_NOT_FOUND`, a PSRAM heap at `0x49080000-0x4A000000` seeded with `heap_caps_add_region_with_caps`, `heap_caps_malloc_extmem_enable(16384)`, and the `CONFIG_STATELESS_PSARAM_EXECUTION` marker (typo preserved) - and installs MicroPython's REPL RX ISR instead of skipping UART init. `sdkconfig.stateless` adds single-core (`CONFIG_FREERTOS_UNICORE=y`, `CONFIG_ESP_SYSTEM_SINGLE_CORE_MODE=y`), PMIC split off, HW stack guard off, main-task stack 16384, `CONFIG_SPIRAM_MEMTEST=n`, `CONFIG_PARTITION_TABLE_OFFSET=0x20000`, UART0 115200. `partitions-stateless.csv` is the build-time table (`nvs` 0x6000 / `phy_init` 0x1000 / `factory` 0xC00000, auto-offset); at runtime the payload reads the **loader's** table at 0x20000, which is fine because the shim answers the OTA lookups and no flash app partition is used.

### 11.1 Image contract

| Property | Value |
|---|---|
| Payload image | 3,480,992 B (3.48 MB) |
| Signed bundle | 3,481,584 B |
| Segments | **8** |
| Entry | `0x4FF05382` = `my_entry_point` (internal SRAM) |
| PSRAM XIP segments | `0x48000020` (2,143,584 B), `0x48210020` (1,219,544 B) |
| Direct copies | TCM `0x30100000` / `0x30100540`, L2MEM `0x4FF00000` / `0x4FF05E7C` / `0x4FF17D00`, RTC `0x50108888` (32 B) |
| PSRAM MMU footprint | 3,407,872 B (2 mappings, 6 direct copies) |
| Heap after shim init | 16,250,496 B free / 15,990,784 B largest |
| Stateless markers | `CONFIG_STATELESS_PSARAM_EXECUTION=y`, `CONFIG_SPIRAM_XIP_FROM_PSRAM=y`, unicore |

The RTC segment (32 B at `0x50108888`) is inside the loader's LP-RAM window (`0x50108000-0x50110000`) and is copied directly; unlike Kern it does not overlap the loader's `do_mmu_mapping_and_jump` at `0x50108080`, so no overlap skip fires. The 3.48 MB bundle+image stays in low PSRAM; the shim heap starts at 16.5 MB and the build script refuses bundle+image ≥ `0x1080000`. **No loader change was needed for the Specter image.**

### 11.2 Bundle format and platform binding

The loader's `bl_section_t` layout ("main" header + image + "sign" section), SHA-256 integrity check, and secp256k1 multisig message are unchanged from Phase 9/12. The only Phase 22 addition is the **platform string**: `kern-image-compat.patch` turns the signer's hardcoded `seedsigner_esp32p4` into a `--platform` choice and adds `specter_esp32p4` (plus `kern_esp32p4`) to the loader's accepted-platform table and SD filename probes. The platform field is loader policy, not a new signed-image structure - no format drift against the existing bundle. (A fresh byte-level diff against current upstream `specter-bootloader` was not part of this run; the Phase 9/12 baseline remains the reference.)

### 11.3 Emu result (`logs/specter_emu_stateless_boot.txt`)

- SB V2 first burn on the rev-1.3 route: `secure_boot_v2: Burning public key hash to eFuse` -> `efuse: Virtual efuses enabled: Not really burning eFuses` -> `Secure boot permanently enabled`.
- Loader: `Specter bootloader section detected` -> `Platform accepted: specter_esp32p4` -> `Performing secp256k1 multisig verification...` -> `Signature verification PASSED!`.
- `Image OK: 8 segments, entry=0x4FF05382` -> `Ready to boot payload at entry 0x4FF05382 (6 direct copies, 2 MMU mappings)`.
- `JMP[1..7]` -> `=== __wrap_call_start_cpu0 ENTERED ===` -> MicroPython stage 0/1 init -> `[P22-S] heap add rc=0 free=16250496 largest=15990784` -> `uart_stdout_init: REPL RX ISR installed`.
- Frozen Specter `main.py` runs: `pyb: 'LED(4)' nao existe nesta placa; usando stub inerte` and `pyb: 'UART('YB')' ...` (the `platform` module init). The MicroPython REPL banner is **not** printed because `main.py` runs before the friendly-REPL prompt and does not return.
- Then the app stops in the first hardware call. `logs/specter_emu_gdb_bt.txt` (attached over `--gdb 1234`):

```
#4  esp_lcd_new_dsi_bus (...) at components/esp_lcd/dsi/esp_lcd_mipi_dsi_bus.c:98
#5  p4board_display_init () at ports/esp32p4/components/p4board/display.c:278
#6  tft_init () at ports/esp32p4/components/lvgl_p4/lv_p4_hal.c:65
#7  display_init () at ports/esp32p4/components/lvgl_p4/moddisplay.c:60
#9  mp_execute_bytecode (...) at py/vm.c:1069
#16 pyexec_frozen_module (name="main.py") at shared/runtime/pyexec.c:770
#17 pyexec_file_if_exists ("main.py") at shared/runtime/pyexec.c:746
#18 mp_task (...) at ports/esp32/main.c:170
```

Line 98 is the `while (!mipi_dsi_phy_ll_is_pll_locked(hal->host)) vTaskDelay(1);` wait. This is the **same absent-DSI-panel boundary as Kern**, reached through Specter's Python app instead of `app_main()` - not a loader, bundle, or shim failure. The emu overlay skips the anti-phishing flash fill (`EMU: skipping anti-phishing flash fill & proof for fast testing`), so the BIP-39 proof remains a hardware-only check.

### 11.4 Compatibility findings

1. **qstr scan hits Linux `MAX_ARG_STRLEN` with LVGL.** The CMake qstr rule expands all 2,239 source paths into one 176,317-byte recipe; `make` runs it via `/bin/sh -c "<recipe>"`, and the single 176 KB argument exceeds the 128 KB `MAX_ARG_STRLEN`, so the build dies with `Argument list too long` before `makeqstrdefs.py` runs. `micropython-stateless.patch` now generates a response file with `file(GENERATE)` and passes `sources @qstr_sources.txt`; `makeqstrdefs.py` expands it. This is a build-system fix, not stateless-specific (any large usermod set hits it), and it keeps the recipe under the limit without shortening the build path.
2. **`_boot.py` must be skipped under stateless execution.** There is no flash filesystem to mount, and the frozen `_boot.py` VFS mount would fail. `ports/esp32/main.c` skips it under `CONFIG_STATELESS_PSARAM_EXECUTION`; frozen `main.py` still auto-runs.
3. **`esp_ota_get_running_partition()` is NULL under the shim.** `ports/esp32/esp32_partition.c` now raises `OSError(ENOENT)` instead of dereferencing NULL when MicroPython's `machine.Partition` wraps it.
4. **The REPL RX ISR needs the port's handler exported.** `ports/esp32/uart.c` drops `static` from `uart_irq_handler` so `__wrap_uart_stdout_init` can install it. The ISR is installed (log line above), but with the stock `main.py` auto-running and blocking in display init, no interactive REPL is reachable; the REPL exists for the case where the app returns/raises. Getting an interactive prompt would require a headless display stub or skipping `main.py`, which is out of this track's scope.
5. **The payload-local partition table never runs.** The image is built against `partitions-stateless.csv` at 0x20000 (same offset as the loader's table), but at runtime the loader's table is what `esp_partition` reads. That is tolerated because the shim answers the OTA lookups and the app does no flash app-partition access before the display stall; persistent app state (NVS) can use the loader's `nvs` partition. This is the same stateless-vs-app-state boundary documented for Kern (§10.1.4).
6. **Sandman's port is a proof-of-concept.** No audit, no mainnet, no production claim; it is used here only as a foreign MicroPython firmware to exercise the loader boundary.

### 11.5 Hardware result (physical P4 rev 1.3, Oct 20, 2026)

Board attached again on Oct 20 (`/dev/ttyACM0`, ESP32-P4 rev v1.3, MAC `e8:f6:0a:e0:ec:44`). The loader was rebuilt from clean `976ee3a` + **only** `kern-image-compat.patch` (no Phase 21 emulator overlay) with the virtual-eFuse defaults and flashed `0x2000`/`0x20000`/`0x30000`; both generated configs were checked to carry `CONFIG_EFUSE_VIRTUAL=y` + `CONFIG_EFUSE_VIRTUAL_KEEP_IN_FLASH=y` before flashing. The signed bundle was pushed to the card over UART with the RAM-only `sd_upload.py` (no card ejection, no flash/eFuse calls) after deleting the old Kern bundle stored as `seedsigner_esp32p4.bin` (the loader probes that name first).

**Loader chain (log `logs/specter_hw_stateless_boot.txt`):**

- `eFuse virtual mode is enabled ... FOR TESTING ONLY` -> `[Virtual] try loading efuses from flash: 0x28000` - the virtual state persisted from the Kern hardware run; no physical burn.
- `SD card mounted at /sdcard` -> `Unmounting SD card before verification (TOCTOU-safe)...` -> `Loaded 3481584 bytes from /sdcard/specter_esp32p4.bin` -> `Specter bootloader section detected` -> `Platform accepted: specter_esp32p4` -> `Performing secp256k1 multisig verification...` -> `Signature verification PASSED!`.
- Anti-phishing proof `wonder echo bomb balcony` - the fill provisioned during the Kern run is reused via the NVS magic (no refill); the words match `logs/kern_stateless_loader_hw.txt`.
- `Image OK: 8 segments, entry=0x4FF05382` -> `JMP[1..7]` -> `=== __wrap_call_start_cpu0 ENTERED ===` -> `[P22-S] heap add rc=0 free=16250496 largest=15990784` -> `uart_stdout_init: REPL RX ISR installed` -> frozen `main.py` pyb stubs.
- The `W: ldo: The voltage value 0 ...` line appears at the same timestamp in the Kern hardware log; it is the SD power-control default warning, not a regression.

**Silicon boundary (diagnostics):** `specter_changes/hw-diag-main-prints.patch` adds `print()` markers (the app builds with `CONFIG_LOG_DEFAULT_LEVEL_ERROR`, so its own `ESP_LOGI` success lines are invisible), and `hw-diag-display-markers.patch` adds `ESP_LOGE` step markers in `p4board_display_init()`.

- **Emu prediction confirmed:** the on-chip DSI PHY PLL **does lock with no panel attached**. Silicon gets past the emulator's stall point (`[P22-DIAG] dsi bus ok`) through `dbi io ok`, `dpi panel ok`, `callbacks ok`, `reset_lcd ok`, and then blocks inside `send_st7701_init()` - the ST7701 command sequence over the DBI link, with no panel attached. Log: `logs/specter_hw_display_diag2.txt`.
- **With the ST7701 sequence skipped** (same patch, diagnostic only), display init returns: `frame buffers ok` -> `lv-p4: touch init failed; the UI will be display-only` (GT911 absent) -> `[P22-DIAG] main: display.init returned` -> `sdram mounted` -> `starting Specter GUI`. The app then enters its own error path: `E lcd.dsi: can't fetch data ... underrun` and `print(e)` at `Specter.handle_exception()` emits `[Errno 19] ENODEV`, followed by an app-level `SW_CPU_RESET` loop. That is app-side behavior with no panel/touch and the stateless SD/LDO state - Phase 23 (app boot) territory, not a loader or bundle failure. Logs: `logs/specter_hw_display_skip_diag.txt`, `logs/specter_hw_gui_diag.txt`.

**Serial capture:** `idf.py monitor` refuses to run without a TTY, so the hardware logs were captured with the new `Phase_22/tools/capture_serial.py` (plain pyserial; parks DTR/RTS deasserted for normal boot, pulses RTS to reset, writes a raw log). Read-only with respect to flash and eFuses.

**Hardware reproduce:** build the loader from a clean `976ee3a` tree + the two gitignored signing keys + `kern-image-compat.patch` only (no `EMU_FLASH_PAYLOAD`), with `idf.py -B build-hw -D IDF_TARGET=esp32p4 -D SDKCONFIG=build-hw/sdkconfig -D "SDKCONFIG_DEFAULTS=$PWD/sdkconfig.defaults;$PWD/sdkconfig.defaults.esp32p4" reconfigure && idf.py -B build-hw build`; verify `CONFIG_EFUSE_VIRTUAL=y`/`KEEP_IN_FLASH=y` in `build-hw/sdkconfig` and `build-hw/bootloader/config/sdkconfig.h`; flash `0x2000` bootloader, `0x20000` ptable, `0x30000` app with `esptool.py --chip esp32p4`; push the bundle with `sd_upload.py --chip esp32p4 --uploader-bin uploader/build/esp32p4/seedsigner_sd_uploader.bin upload --name specter_esp32p4.bin <bundle>`; capture with `Phase_22/tools/capture_serial.py --reset --seconds N -o <log>`. Expected: verified hand-off into the frozen app; the stock bundle then blocks in the display tree (`send_st7701_init`) on the headless devkit. The exact flashed loader build (bootloader, partition table, app + ELF/MAP and its `sdkconfig`) is archived in `Phase_22/build/hw-loader/`.

### 11.6 Specter acceptance status

| Check | Result |
|---|---|
| Built for P4 pre-v3 | sandman `f54e345`, MicroPython `8cf130db34`, IDF 5.5, `REV_LESS_V3=y` |
| Image fits loader mapping | 8 segments, 3.48 MB, entry `0x4FF05382` |
| Signed bundle `specter_esp32p4` | `Signature verification PASSED!` (emu + silicon) |
| SB V2 | virtual-eFuse route; state persisted from the Kern run, no physical burn |
| Specter secp256k1 multisig | PASSED |
| JMP + PSRAM execution | `JMP[1..7]`, shim, MicroPython app entry |
| App-level UART milestone | frozen `main.py` running; silicon boundary pinned inside `send_st7701_init()`; with a diagnostic panel-skip the app reaches `Specter.start()` |
| Physical P4 SD boot | `logs/specter_hw_stateless_boot.txt` |
| No flash app partition | SD bundle only (emu flash injection for the emu route) |
| Zero physical eFuse burns | virtual eFuse only |
| Display/camera UI, mainnet | not claimed (headless devkit, no DSI panel/touch) |

**Reproduce:** `RUN_EMU=0 ./Phase_22/tools/build_specter_stateless_emu.sh` (build/sign/merge) or `RUN_EMU=1 ...` (boot). `EMU_GDB=1` adds the GDB stub. The script rebuilds from clean archives each run; the first configure needs network for the 14 managed components.

**Next:** Phase 23 (app boot) picks up from the pinned silicon boundary - the stock `send_st7701_init()` block on an absent panel and the app's own `ENODEV`/reset path when the panel sequence is skipped. Per-platform key slots remain a follow-up isolation item (§10.1.5), not a Phase 22 gate.
