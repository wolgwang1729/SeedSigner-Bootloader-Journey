# Phase 21: Headless Boot Emulator - Stateless Boot Chain on esp-emu

- **Date:** October 17, 2026 (Updated October 20, 2026)
- **Author:** Mayank (wolgwang)
- **Project:** SeedSigner Secure Boot — Independent Continuation
- **Status:** Complete - Full stateless boot chain verified on esp-emu v0.50.0 (October 20, 2026). Zero physical eFuse operations performed.
- **Hardware:** Emulated ESP32-P4 (rev 1.3 and rev 3.1) and ESP32-S3 targets via esp-emu v0.50.0. Physical hardware unneeded.
- **Scope Notice:** Headless pre-silicon emulation campaign enabling full verification of the stateless Secure Boot V2 chain, partition tables, and payload handoff in software. Operates via scratch overlays outside the mainline repository.

---

## 1. Overview & Motivation

While physical hardware procurement for display and camera modules remained blocked by regional supply chain constraints, engineering progress on the core boot pipeline could not afford to stall. The stateless secure bootloader chain represents the critical foundation upon which all downstream phases depend.

Phase 21 established a headless pre-silicon emulation environment capable of exercising the complete boot and verification pipeline in software. By executing identical binary artifacts within an instruction-accurate emulator, the entire cryptographic chain (Secure Boot V2 RSA-PSS, partition validation, Specter secp256k1 multisig verification, TRNG flash-fill anti-phishing hashing, and Cache MMU execution handoff) is validated without consuming development silicon or requiring physical hardware.

### Key Milestones Achieved
1. **Full Stateless Chain Execution:** Verified end-to-end stateless execution across both ESP32-S3 and ESP32-P4 architectures, including faithful fail-closed halts when SD storage is absent.
2. **Dual-Architecture MicroPython Execution:** Booted stock MicroPython images to interactive REPL prompts over a bridged TCP socket on both ESP32-S3 and ESP32-P4 rev 1.3 targets.
3. **Automated Continuous Integration (GitHub Actions):** Directly enabled an automated end-to-end testing pipeline in GitHub Actions (`.github/workflows/ci.yml` in the bootloader repository). Previously, pull requests could only run host unit tests, while hardware tests were skipped on cloud runners due to absent physical dev boards and SD cards. By deploying `esp-emu v0.50.0` in GitHub Actions (`emulator-repl` matrix job), every push and pull request now builds the bootloader, signs the MicroPython payload, boots the full stateless chain in software, and verifies interactive REPL command execution across both ESP32-P4 and ESP32-S3 targets on standard `ubuntu-latest` cloud runners.
4. **Upstream Emulator Contribution & MMU Fix:** Identified a critical dynamic Cache MMU translation gap on ESP32-P4 in `esp-emu <= 0.49.0`. Raised upstream issue [espressif/esp-emulator#24](https://github.com/espressif/esp-emulator/issues/24), which upstream maintainers resolved in `esp-emu v0.50.0` ([maintainer confirmation](https://github.com/espressif/esp-emulator/issues/24#issuecomment-6294111550)). This allowed retiring all temporary jump workarounds.
5. **Upstream Feature Request for SD Card Emulation:** Submitted upstream feature request [espressif/esp-emulator#33](https://github.com/espressif/esp-emulator/issues/33) proposing host-backed SD card (SDMMC/SDSPI) storage emulation to enable native FAT32 image testing in headless continuous integration.
6. **Mainline Bootloader Regression Resolved:** Uncovered a silent 32-byte image-header staging regression in the bootloader's modular refactor, verified the fix in emulation, and successfully landed commit `0361736` in the mainline repository.
7. **Mainline Repository Isolation:** The primary bootloader repository remained pristine; emulation-specific flash-injection hooks reside purely in local scratch overlays applied dynamically at test time.

---

## 2. Emulator Evaluation & Toolchain Selection

| Candidate Emulator | ESP32-P4 Support | ESP32-S3 Support | SD Card Storage | Verdict |
|---|---|---|---|---|
| **QEMU (Espressif fork)** (bundled with ESP-IDF v6.1 `esp_develop_9.2.2`) | Unsupported (no `esp32p4` machine model exists) | Supported (machine exists) | Unsupported (not modeled) | **Rejected** (cannot emulate P4 architecture) |
| **Wokwi / Renode** | Unsupported (no maintained P4 board targets) | Partial | Unsupported | **Rejected** (insufficient architectural fidelity) |
| **esp-emu v0.50.0** (Espressif Rust emulator) | Supported (ROM, PSRAM, and dynamic S-MMU modeled) | Supported (full ROM and PSRAM modeled) | Unsupported (open feature request) | **Chosen** (high fidelity, actively maintained) |

### Toolchain Evaluation Notes
- **QEMU Architectural Limitations:** Auditing the latest ESP-IDF v6.1 QEMU binary confirmed that Espressif's QEMU fork has no machine model for the ESP32-P4. Historical scripts in earlier project archives labeled "P4 QEMU" actually executed `-machine esp32s3`.
- **esp-emu Storage Model:** While `esp-emu` models CPU cores, internal RAM, external PSRAM, and flash controllers accurately, neither SDMMC nor SDSPI host controllers are modeled. Consequently, without modification, unmodified loaders halt fail-closed on card initialization timeouts.
- **Flash Injection Overlay:** To supply payload binaries in emulation without compromising the production verification path, a lightweight scratch patch ([loader_changes/emu-flash-payload.patch](./loader_changes/emu-flash-payload.patch)) was developed. Under `#ifdef EMU_FLASH_PAYLOAD`, the loader reads the signed Specter bundle from raw flash offset `0x13FF00` via `esp_rom_spiflash_read`, landing the inner payload at the 64 KB-aligned offset `0x140000`. All cryptographic hash and signature checks remain 100% active.

---

## 3. Emulator Engineering Findings (E1 through E9)

| ID | Phenomenon Observed | Root Cause Analysis | Resolution / Workaround | Silicon Impact |
|---|---|---|---|---|
| **E1** | P4 bootloader in silicon configuration panics inside 2nd-stage bootloader with `Load access fault` dereferencing `rom_spiflash_legacy_data` (`MTVAL: 0x00000019`). | Physical dev boards use rev 1.x silicon (`CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y` with ROM helpers at `0x4FF3FFE8`); `esp-emu` default model represents rev 3.x/eco5 ROM (helpers at `0x4FFBFFE8`). Pre-v3 bootloader dereferences an unmapped null page. | Appended configuration fragment [tools/emu_rev_p4.defaults](./tools/emu_rev_p4.defaults) (`CONFIG_ESP32P4_REV_MIN_301=y`) for eco5 emulation runs. | **None** - Physical silicon builds remain `REV_MIN_0`. |
| **E2** | *(Disproven)* Alleged P4 Secure Boot V2 digest burn failure in `esp-emu`. | Early test runs crashed due to E1 ROM mismatches, which was initially suspected to be an SB-V2 digest-burn flaw. | Disproven. Revision-matched builds prove Secure Boot V2 functions 100% faithfully: first-boot RSA digest burn to virtual eFuses, second-boot signature verification, and bundle checks all pass cleanly. | **None** - Secure Boot V2 is verified active across both emu and silicon. |
| **E3** | S3 bootloader boots unmodified in `esp-emu` through complete Secure Boot V2 first-burn sequence. | Emulated S3 ROM revision matches production build defaults (rev 0.x). | No configuration fragments needed; executes out of the box. | **None** - Identical to silicon behavior. |
| **E4** | Both P4 and S3 loaders halt fail-closed with `SDMMC mount failed (ESP_ERR_TIMEOUT)`. | Neither SDMMC nor SDSPI host hardware is modeled in `esp-emu`. | Accepted as a positive proof of fail-closed security: missing storage triggers a safe halt. | **None** - Proves fail-closed property. |
| **E5** | Inability to feed payload to loader when SD card is absent. | Emulation lacks physical SD card peripheral. | Developed `EMU_FLASH_PAYLOAD` scratch overlay reading signed bundle from flash offset `0x13FF00`. Cryptographic multisig verification is untouched. | **None** - Staging source changes only; verification is identical. |
| **E6** | MicroPython REPL echoes typed characters over TCP socket but never evaluates expressions. | MicroPython `readline` evaluates commands strictly upon receiving a carriage return (`\r`); terminal emulators typically transmit newline (`\n`), which readline absorbs. | Developed [tools/repl_client.py](./tools/repl_client.py) to bridge TCP console socket and append `\r` to all outgoing lines. | **None** - Standard MicroPython terminal behavior. |
| **E7** | P4 MicroPython execution diverges across silicon revision models. | `esp-emu` default P4 model is rev 3.1 eco5 (retention RAM at `0x4FF7B000`); physical boards and builder repos target rev 1.x (retention RAM at `0x4FF30000`). Pre-v3 builds store-fault in heap init on the v3.1 model. | Resolved via rev-matched emulation: `--rom esp32p4_rev0_rom.elf` + `--efuse` blob from [tools/make-efuse.py](./tools/make-efuse.py). Pre-v3 MicroPython boots to interactive REPL. | **None** - Physical boards target rev 1.x silicon. |
| **E8** | On rev-1.3 route, hello payload aborts immediately following `JMP[7]`: `Invalid app image header` + `abort()`. | **Mainline Bootloader Regression:** The modular refactor (`354e0bf`) dropped 32-byte image-header staging in `main/esp_image.c`. IDF `system_early_init()` reads `esp_image_header_t` from `&_rodata_reserved_start - 32`, finding zeros. | Restored 32-byte staging header. Fix verified in emulation and landed in bootloader mainline as commit `0361736`, verified on physical P4 silicon. | **Silicon confirmed** - Resolved upstream. |
| **E9** | P4 runtime Cache MMU remap ignored by emulator translation: S-MMU programmed correctly (`0xC04`), but memory accesses translate flat (`paddr = vaddr - 0x48000000`), trapping with `Illegal instruction 0x00000000`. | **Upstream Emulator Bug:** `esp-emu <= 0.49.0` latched S-MMU register writes but did not consult the translation table in the memory-bus router for PSRAM accesses (`0x48000000..0x4C000000`). | **Fixed Upstream:** Raised issue [espressif/esp-emulator#24](https://github.com/espressif/esp-emulator/issues/24). Upstream maintainers fixed translation in `esp-emu v0.50.0`. Temporary `JMP[6.5]` identity-copy workaround retired. | **None** - Physical silicon always routes through S-MMU correctly. |

---

## 4. Upstream Contributions & Community Issues

During the execution of Phase 21, two significant upstream issues were submitted to the Espressif `esp-emulator` project to advance embedded emulation tooling:

### 4.1 Upstream Issue: Dynamic Cache MMU Translation Fix
- **Issue Reference:** [espressif/esp-emulator#24](https://github.com/espressif/esp-emulator/issues/24)
- **Title:** `[ESP32-P4] Dynamic Cache MMU translation (SPI_MEM_S_MMU_ITEM_CONTENT_REG @ 0x5008E37C) not wired to PSRAM address space (0x48000000..0x4C000000)`
- **Problem Raised:** In `esp-emu v0.49.0`, writing S-MMU entries (e.g. entry 0 = `0xC04` mapping `0x48000000 -> paddr 0x00040000`) latched the register values, but address translation for instruction fetches and data reads remained flat (`paddr = vaddr - 0x48000000`). Consequently, any stateless loader that places code at physical offsets trapped immediately upon jump with `Illegal instruction 0x00000000`.
- **Upstream Resolution:** Espressif maintainers resolved the issue in **esp-emu v0.50.0** with the release note *"ESP32-P4 PSRAM window follows the PSRAM MMU"* ([maintainer comment](https://github.com/espressif/esp-emulator/issues/24#issuecomment-6294111550)).
- **Impact on Project:** Allowed immediate retirement of the temporary `JMP[6.5]` identity-copy workaround in [loader_changes/emu-flash-payload.patch](./loader_changes/emu-flash-payload.patch). Verified on unmodified production remap paths for both C payloads and stock MicroPython.

### 4.2 Upstream Feature Request: Host-Backed SD Storage Emulation
- **Feature Request Reference:** [espressif/esp-emulator#33](https://github.com/espressif/esp-emulator/issues/33)
- **Title:** `[Feature] SD card storage: SDMMC/SDSPI host model backed by a host card image`
- **Proposal Submitted:** Proposed adding register-level and block-level emulation for SDMMC and SDSPI host controllers, backed by host raw filesystem images (`--sd <path.img>` and `--sd-read-only`).
- **Use Cases Detailed:** Highlighted the need for headless automated regression testing of stateless bootloaders (such as SeedSigner), filesystem drivers (`fatfs`), and firmware update verification in continuous integration pipelines without physical card wear.

### 4.3 Integration into Mainline GitHub Actions CI
The headless emulation framework established in Phase 21 directly solves a long-standing continuous integration limitation for embedded hardware:
- **Prior CI Limitation:** In `seedsigner-esp32-bootloader`, automated GitHub Actions workflows could only run host C++ unit tests (`host-tests` job) and build firmware binaries. The integration test step (`Run Hardware Tests`) was marked `continue-on-error: true` because standard cloud runners lack physical `/dev/ttyACM0` serial devices and microSD cards.
- **Emulation in Cloud CI:** Using the artifacts and scripts proven in this phase, a dedicated `emulator-repl` matrix job was implemented in the bootloader repository's `.github/workflows/ci.yml`. On every commit and pull request, GitHub Actions:
  1. Installs pinned `esp-emu v0.50.0` directly into the `ubuntu-latest` runner environment.
  2. Downloads the matching ESP32-P4 rev0 ROM ELF (`esp32p4_rev0_rom.elf`) for rev-1.3 route execution.
  3. Uses `tools/emu/run_emu_ci.sh` to compile the bootloader, sign the MicroPython payload, and merge the flash image.
  4. Boots the emulator headlessly, verifies Secure Boot V2 and Specter multisig verification, and confirms that the MicroPython REPL evaluates injected commands.
  5. Uploads raw emulator execution logs as downloadable GitHub Actions artifacts.
- **Impact:** The entire security boot chain and runtime payload execution are now regression-tested on cloud runners without physical dev boards.

---

## 5. Reproduction Runbook

### Prerequisites
- ESP-IDF v5.5 exported (`source ~/esp/esp-idf-v5.5/export.sh`).
- `esp-emu >= 0.50.0` installed at `~/.local/bin/esp-emu`.
- Python 3 dependencies: `pip install ecdsa bech32`.

### Execution Commands

#### 1. S3 Faithful Boot (Secure Boot V2 Enabled -> Fail-Closed SD Halt)
```bash
./tools/run_emu.sh s3-halt
```
*Expected result: S3 Secure Boot burns virtual eFuses, verifies loader signature, and halts cleanly with `SDMMC mount failed (ESP_ERR_TIMEOUT)`.*

#### 2. P4 Faithful Boot (Secure Boot V2 Enabled -> Fail-Closed SD Halt)
```bash
./tools/run_emu.sh p4-halt
```
*Expected result: P4 Secure Boot burns virtual eFuses, verifies loader signature, and halts cleanly with `Failed to mount SD card`.*

#### 3. S3 End-to-End Stateless Boot (MicroPython REPL)
```bash
SCRATCH=/tmp/emu_phase21_mp \
PAYLOAD_BIN=path/to/micropython_s3.bin \
  ./tools/run_emu.sh s3-e2e
```
*Expected result: Boots through multisig verification, derives anti-phishing words `cruel push unusual adapt`, remaps MMU, and opens MicroPython REPL.*

#### 4. P4 rev-1.3 End-to-End Stateless Boot (Stock MicroPython REPL)
```bash
SCRATCH=/tmp/emu_phase21_p4_rev13 \
PAYLOAD_BIN=path/to/pre-v3-micropython.bin \
  ./tools/run_emu.sh p4-rev13-e2e
```
*Expected result: Uses rev0 ROM and rev1.3 virtual eFuse blob, executes multisig verification, and boots stock pre-v3 MicroPython to interactive `>>>` prompt.*

#### 5. Interactive TCP Console Connection
In a separate terminal, while `esp-emu` is running with `--uart-tcp 127.0.0.1:5555`:
```bash
python3 tools/repl_client.py
```
*Type Python expressions (`1+1`, `import sys; print(sys.platform)`). Line input is sent with `\r` and evaluates live.*

---

## 6. Execution Results & Log Analysis

All test runs are archived with complete UART captures in [logs/](./logs/):

### 6.1 ESP32-S3 Results
- **Fail-Closed SD Halt ([logs/s3_sd_halt.txt](./logs/s3_sd_halt.txt)):** Layer 1 Secure Boot V2 initializes, derives RSA public key hash, burns virtual eFuse `EFUSE_BLK_KEY0`, and verifies loader signature on warm reboot. Halts cleanly upon absent SD card.
- **Hello Shim Stateless Execution ([logs/s3_hello_e2e.txt](./logs/s3_hello_e2e.txt)):** Bundle verification succeeds, flash fill provisions 5.875 MB, deriving proof words `arctic melody humor slow`. Payload prints `Hello world!` across 8 reboot cycles with identical words.
- **MicroPython REPL Execution ([logs/s3_mp_repl.txt](./logs/s3_mp_repl.txt)):** Boots to `MicroPython v1.27.0` banner. Evaluates commands interactively over TCP socket (`print('emu21-repl-ok') -> emu21-repl-ok`).

### 6.2 ESP32-P4 Results
- **Fail-Closed SD Halt ([logs/p4_sd_halt.txt](./logs/p4_sd_halt.txt)):** First boot generates RSA-PSS digest and virtual eFuse burn; loader prints banner and halts fail-closed on unmodeled SD hardware.
- **Hello Shim Stateless Execution ([logs/p4_hello_boot_e2e.txt](./logs/p4_hello_boot_e2e.txt)):** Executes 46 consecutive reboot cycles in a single 600-second session.
- **MicroPython Interactive Execution on rev-1.3 ([logs/p4_rev13_mp_repl_input.txt](./logs/p4_rev13_mp_repl_input.txt)):** Under rev-matched emulation (`esp32p4_rev0_rom.elf` + rev1.3 eFuse blob), stock pre-v3 MicroPython executes injected commands cleanly: `print("P4MP-REPL-OK", 2+2) -> P4MP-REPL-OK 4`.
- **MMU-Fixed Verification on esp-emu v0.50.0 ([logs/p4_rev13_hello_mmu_fixed_e2e.txt](./logs/p4_rev13_hello_mmu_fixed_e2e.txt), [logs/p4_rev13_mp_mmu_fixed_e2e.txt](./logs/p4_rev13_mp_mmu_fixed_e2e.txt)):** Confirms that upstream fix for issue #24 allows unmodified production S-MMU remapping (`0xC04`/`0xC05`) to translate dynamically, executing 230 cycles in 240 seconds without identity copies.

---

## 7. Scope Boundaries & Silicon Disclaimer

To maintain technical accuracy across the project lifecycle:
1. **Pre-Silicon Regression Only:** Headless emulation serves as a fast CI regression test rig. It is never treated as a final acceptance gate for hardware security claims.
2. **Hardware Features Unmodeled:** Physical eFuse one-time programming, physical fault injection, external RF performance, and display/camera DMA bus contention require physical dev boards.
3. **No Mainline Changes:** The mainline repository (`seedsigner-esp32-bootloader`) took zero emulation-specific commits. Emulation hooks operate purely through scratch overlays.

---

## 8. Deliverable Artifacts & File Map

| File Path | Description |
|---|---|
| [Phase_21_Headless_Boot_Emulator.md](./Phase_21_Headless_Boot_Emulator.md) | Main Phase 21 engineering documentation. |
| [loader_changes/emu-flash-payload.patch](./loader_changes/emu-flash-payload.patch) | Emulation scratch overlay enabling raw flash bundle ingestion at `0x13FF00`. |
| [loader_changes/README.md](./loader_changes/README.md) | Overlay documentation and retirement notes for image-header staging and identity-copy workarounds. |
| [tools/run_emu.sh](./tools/run_emu.sh) | Automated one-command test driver supporting `s3-halt`, `p4-halt`, `s3-e2e`, `p4-e2e`, and `p4-rev13-e2e`. |
| [tools/emu_rev_p4.defaults](./tools/emu_rev_p4.defaults) | Configuration fragment for rev 3.1 eco5 emulation matching. |
| [tools/emu_nosb.defaults](./tools/emu_nosb.defaults) | Historical debug fragment retained for documentation. |
| [tools/repl_client.py](./tools/repl_client.py) | Interactive terminal bridge client ensuring carriage-return line termination. |
| [tools/make-efuse.py](./tools/make-efuse.py) | Upstream helper generating virtual eFuse binary blobs for silicon revision matching. |
| [tools/README.md](./tools/README.md) | Tool documentation and usage runbook. |
| [logs/](./logs/) | 14 raw UART telemetry logs capturing S3 and P4 execution benchmarks. |
