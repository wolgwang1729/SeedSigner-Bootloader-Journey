# Phase 20: Reversible Security R&D & Alternate Boot Paths

- **Date:** October 16, 2026
- **Author:** Mayank (wolgwang)
- **Project:** SeedSigner Secure Boot — Independent Continuation
- **Status:** Complete - R0 through R8 closed on physical silicon (October 16, 2026). Zero irreversible eFuse burns (virtual eFuses only; `espefuse.py` never invoked).
- **Hardware:** ESP32-P4-WIFI6-DEV-KIT headless (v1.3, 16 MB flash; target `WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43`, LCD and camera initialization skipped or tolerated). ESP32-S3 frozen at Phase 17 semantics.
- **Scope Notice:** Reversible headless security research and development evaluating alternate architectural designs, cryptographic algorithms, memory models, and fail-closed protections. Operating completely outside the mainline bootloader repository via standalone test payloads, host tools, and modular patches.

---

## 1. Overview & Research Objectives

The production stateless bootloader chain was successfully proven across physical ESP32-P4 silicon (Phases 9-14) and ESP32-S3 silicon (Phases 15-17):

> Secure Boot V2 (RSA-3072, virtual eFuses) -> SD card mount (ESP32-P4 on-chip LDO4) -> whole bundle into PSRAM -> **immediate unmount (anti-TOCTOU)** -> Specter secp256k1 multisig verification (`seedsigner_esp32p4` platform binding, `pl_ver` floor check) -> TRNG `random_fill` partition SHA-256 -> **4 BIP-39 words printed over UART** -> JMP-zone Cache MMU remap -> MicroPython REPL.

While this architecture guarantees high security on hardware, it represents a single rigid point in an expansive architectural design space:
- **Layer 1 Dependency:** If hardware Secure Boot V2 is unprovisioned or disabled, does Layer 2 (Specter multisig) alone fail closed against payload tampering?
- **Hardware Binding Without Physical Burns:** Before committing to irreversible eFuse burns (HMAC KEY5 binding and monotonic `SECURE_VERSION` counters), what are the strongest reversible, software-bound anti-phishing and anti-rollback guarantees achievable?
- **Signature Cryptography:** Is secp256k1 multisig the optimal performance trade-off compared to P-256 ECDSA or ed25519 on resource-constrained RISC-V and Xtensa cores?
- **Execution Handoff:** Can simple internal-SRAM payloads boot reliably without the intricate Cache MMU and literal-placement requirements of the PSRAM-XIP JMP zone?
- **Storage Race Conditions:** Does the "read -> unmount -> verify" sequence provide complete immunity against power loss, mid-stream write tears, and media swap attacks?

Phase 20 resolves these questions by developing and testing eight alternate routes (**R0 through R8**) on physical silicon. Each route is constructed to either pass or be rejected based on empirical evidence, using a falsifiable **CONTROL vs PATCHED** boot pair.

---

## 2. Hard Security Boundaries & Threat Model

Every experiment in Phase 20 conforms to strict, non-negotiable engineering constraints:

1. **Zero Irreversible eFuse Actions:** Virtual eFuses remain active (`CONFIG_EFUSE_VIRTUAL=y` and `CONFIG_EFUSE_VIRTUAL_KEEP_IN_FLASH=y`). The virtual store resides in the dedicated flash partition `efuse` and is fully recoverable via `esptool.py erase_region`. `espefuse.py`, `idf.py burn-efuse`, and hardware security register locks are never executed.
2. **Reversible Flash Operations Only:** All flash operations preserve the original device state. Prior to testing, a full flash backup is captured ([flash_backup_20261016.bin](./logs/flash_backup_20261016.bin)), and the device is verified to restore cleanly.
3. **Headless Execution Verification:** Every proof relies strictly on UART console output, automated python drivers, and timing logs. Display and camera peripherals remain detached; no virtual framebuffer overhead (Phase 18 is deprecated).
4. **Mainline Repository Isolation:** The primary bootloader repository takes zero direct commits from this phase. All modifications ship as modular patches in `./loader_changes/` and standalone code in `./test_payloads/` and `./tools/`.

### Threat Model Alignment

Phase 20 directly builds upon the Phase 14 security evaluation (attacks A1-A12, tamper tests T1-T16, and fault injections F1-F7). Each route explicitly documents which attack vectors remain closed, which are re-opened, and what falls outside its threat envelope:
- Reversible protections defend against casual evil-maid attacks, remote downgrades, and transmission corruption.
- Physical chip decapping, cold memory transplantation, and flash-loader tampering with local physical flasher access require permanent silicon lockdown (Phase 24).

---

## 3. Experimental Methodology & Verification Framework

All evaluations follow a standardized experimental protocol:
1. **CONTROL vs PATCHED Comparison:** For each route, a baseline CONTROL run establishes vulnerability or behavior, followed by a PATCHED run demonstrating protection.
2. **Automated Serial Driving:** The host-side driver ([canary_session.py](./tools/canary_session.py)) orchestrates test commands (`plant`, `status`, `selftest`, `fault_*`), coordinates resets, and streams timestamped transcripts directly into `./logs/`.
3. **Memory Overlap Gate:** The overlap assertion tool ([check_canary_overlap.py](../Phase_19/tools/check_canary_overlap.py)) confirms that newly built payload images never encroach upon canary buffers, staged bundles, or JMP execution zones.
4. **Cryptographic Interop Verification:** Cryptographic primitives evaluated on-device are independently recomputed and verified by host tools ([verify_r3.py](./tools/verify_r3.py), [verify_r7.py](./tools/verify_r7.py)).
5. **Clean Restoration:** After evaluating each route, flash memory is restored to the production Secure Boot V2 baseline, verified via 5-point to 8-point regression checks.

---

## 4. Route Evaluations & Silicon Results

### R0: Scrub-After-Use Discipline (MWDT Boundary Closure)

- **Hypothesis:** Phase 19 demonstrated that hardware watchdog resets (MWDT0 / `rst:0x7`) bypass ROM panic hooks by hardware physics, leaving memory intact (`CANARY_REMANENT`). Zeroizing secret data immediately following cryptographic use eliminates this vulnerability without relying on crash handlers.
- **Implementation:** The test payload ([canary_scrub.c](./test_payloads/canary_scrub_r0/main/canary_scrub.c)) introduces `use_and_scrub`. It plants a 1 MB PSRAM pattern and a 4 KB SRAM block, folds their content into an observable accumulator via DJB hash to prove consumption, executes a ROM-safe memory zeroization loop, and verifies that memory contains zeros (`USED_AND_SCRUBBED ok=1`).
- **Physical Silicon Results:**
  - Control run (`scrub_off, plant, fault_hpwdt`): Next boot reports `rst:0x7` with `CANARY_REMANENT` across 262,144 words ([exp_r0-hpwdt_20261016_154916.log](./logs/exp_r0-hpwdt_20261016_154916.log)).
  - Patched run (`use_and_scrub, fault_hpwdt`): Next boot reports `rst:0x7` with `CANARY_CLEARED` across 1,048,576 bytes and `sram_nonzero=0` ([exp_r0-use-and-scrub-v2_20261016_155905.log](./logs/exp_r0-use-and-scrub-v2_20261016_155905.log)).
  - Overhead: The complete plant, consume, and wipe cycle took 42.6 ms.
- **Verdict: ADOPT.** Crash-time sanitization serves as defense-in-depth, but use-time zeroization is strictly required for all firmware handling private key material.

| Run | Injected Commands | Reset Reason | Inspector Verdict | Security Implication |
|---|---|---|---|---|
| 1 | `status`, `selftest` | None | `SELFTEST_OK` | In-situ wipe mechanism functional |
| 2 | `scrub_off, plant, fault_restart` | `rst:0xc` (SW) | `CANARY_REMANENT` | Baseline memory remanence confirmed |
| 3 | `scrub_on, plant, fault_restart` | `rst:0xc` (SW) | `CANARY_CLEARED` | Software crash handler zeroizes RAM |
| 4 | `plant, fault_abort` | `rst:0xc` (SW) | `CANARY_CLEARED` | Assertion abort handler zeroizes RAM |
| 5 | `plant, fault_wdt` | `rst:0xc` (INT-WDT) | `CANARY_CLEARED` | Interrupt watchdog zeroizes RAM |
| 6 | `plant, fault_hpwdt` | `rst:0x7` (HP-WDT) | `CANARY_REMANENT` | Hardware watchdog bypasses software hook |
| 7 | `use_and_scrub, fault_hpwdt` | `rst:0x7` (HP-WDT) | `CANARY_CLEARED` | **Hardware watchdog vulnerability resolved** |

---

### R1: Software-Only Verified Boot (Layer 2 Isolation)

- **Hypothesis:** When Layer 1 hardware Secure Boot V2 is disabled, Layer 2 (Specter secp256k1 multisig) alone fails closed against all modified, untrusted, or downgraded payload bundles.
- **Implementation:** The bootloader was compiled in a scratch directory with `CONFIG_SECURE_BOOT_V2_ENABLED=n`. Negative test bundles were minted using [make_attacks.py](./tools/make_attacks.py) from the active signing key.
- **Physical Silicon Results:**
  - Valid bundle ([r1_good.log](./logs/r1_good.log)): Boots with zero RSA verification log lines; Specter signature check passes, BIP-39 words display, and handoff proceeds to REPL.
  - Raw binary ([r1_raw.log](./logs/r1_raw.log)): Rejected immediately (`raw images are not accepted`).
  - Wrong platform ([r1_wrong-platform.log](./logs/r1_wrong-platform.log)): Rejected (`Invalid platform attribute: 'seedsigner_esp32s3'`).
  - Downgrade attempt ([r1_downgrade.log](./logs/r1_downgrade.log)): Rejected (`Firmware downgrade detected!`).
  - Payload tamper / bad signature ([r1_tamper.log](./logs/r1_tamper.log), [r1_badsig.log](./logs/r1_badsig.log)): Rejected (`Signature verification failed`).
  - Full restoration ([r1_restored.log](./logs/r1_restored.log)): Flash restored to production Secure Boot V2.
- **Verdict: CONFIRMED.** Layer 2 alone provides complete fail-closed protection against malicious SD payloads. The sole property lost is flash-loader authenticity (an evil loader flashed over USB would not be detected without Layer 1).

---

### R2: Reversible Monotonic Anti-Rollback

- **Hypothesis:** A monotonic counter stored in NVS, enforced within the signed payload manifest, prevents downgrade attacks without consuming irreversible hardware eFuses.
- **Implementation:** Patch [r2-rollback.patch](./loader_changes/r2-rollback.patch) adds `rollback.c`. A dedicated 4 KB sector at offset `0x1000` in the `nvs` partition stores `{magic: "ROLB", max_ver: uint32}`. Boot checks `pl_ver >= max_ver`. The test payload provides `wipe_rb` to erase this sector directly via `esp_flash_erase_region`.
- **Physical Silicon Results:**
  - Version 2 bundle boots and advances counter: `Rollback counter advanced 1 -> 2` ([r2_v2.log](./logs/r2_v2.log)).
  - Version 1 bundle rejected: `Firmware rollback refused: pl_ver=1 < stored=2. Halting.` ([r2_v1_refused.log](./logs/r2_v1_refused.log)).
  - Counter erasure: Executing `wipe_rb` from payload context wipes the sector ([exp_r2-wipe-rb_20261016_163047.log](./logs/exp_r2-wipe-rb_20261016_163047.log)).
  - Post-wipe reboot: Version 1 bundle boots cleanly: `Rollback counter initialized at pl_ver=1` ([r2_v1_after_wipe.log](./logs/r2_v1_after_wipe.log)).
- **Verdict: GRADED REVERSIBLE-ONLY.** Provides robust defense against remote or accidental downgrades. However, because any code execution or flash rewrite can reset NVS, it cannot replace hardware eFuse `SECURE_VERSION` counters in production.

---

### R3: Software-Bound Anti-Phishing Words

- **Hypothesis:** Deriving the 4 BIP-39 anti-phishing words from `SHA256(fill_hash || salt || cid_pack)` binds the proof to the specific board and SD card without requiring one-time HMAC eFuses.
- **Implementation:** Patch [r3-salt-bind.patch](./loader_changes/r3-salt-bind.patch) introduces `salt_bind.c`. A 16-byte random salt is provisioned into NVS sector `0x2000`, and 16 bytes of SD card identification (`cid_pack`) are captured before card unmount. Host verifier [verify_r3.py](./tools/verify_r3.py) reads flash contents to mathematically confirm the derivation.
- **Physical Silicon Results:**
  - First boot: Generates salt `0a32945f`, reads CID pack, and derives words `vessel pledge essay oppose` ([r3_bootA_saltA.log](./logs/r3_bootA_saltA.log)). Host tool verifies mathematical match.
  - Normal reboot: Re-reads salt; words remain identical and stable ([r3_bootA_stable.log](./logs/r3_bootA_stable.log)).
  - Salt sector erased: Fresh salt `3f6d54d2` provisioned, words shift to `kitten lift print easily` ([r3_bootB_saltB.log](./logs/r3_bootB_saltB.log)). Host tool verifies mathematical match.
  - Flash tampering: Flipping 1 bit in `random_fill` triggers immediate halt: `FLASH TAMPERED! Hash mismatch` ([r3_tamper.log](./logs/r3_tamper.log)).
  - Provision state erased: 115 s TRNG re-fill completes, deriving `require jacket clay uphold` ([r3_reprovision_wordsC.log](./logs/r3_reprovision_wordsC.log)).
- **Verdict: GRADED REVERSIBLE-ONLY.** Per-board and per-card binding is established reversibly. However, because 4 words represent ~44 bits of entropy and the salt can be extracted from unencrypted flash, it does not achieve the cryptographic collision resistance of a hardware-secret HMAC key.

---

### R4: Signature Scheme & Threshold Evaluation

- **Hypothesis:** Evaluating alternative signature schemes (P-256 ECDSA, ed25519) and multisig thresholds (1-of-1, 1-of-2, 2-of-2) quantifies the performance and memory impact of the release signing policy.
- **Implementation:** Patch [r4-verify-bench.patch](./loader_changes/r4-verify-bench.patch) instruments cycle counters and heap watermarks around `blsig_verify_multisig`. Multi-signature bundles are signed with [sign_multisig.py](./tools/sign_multisig.py). Payload command `bench_p256` measures in-payload P-256 execution.
- **Physical Silicon Results:**
  - 2-of-2 secp256k1 multisig: Verifies in 12,761,530 cycles (~35.4 ms) with 0 heap leak ([r4_2of2.log](./logs/r4_2of2.log)).
  - 1-of-2 presentation under threshold 2: Fails closed in 9,075,354 cycles (~25.2 ms): `1 valid signature(s), need 2` -> `HALT` ([r4_1of2.log](./logs/r4_1of2.log)).
  - Scaling: A single secp256k1 verification takes ~25.2 ms; each additional signature adds ~7-10 ms (~2.5-3.7M cycles).
  - P-256 ECDSA: 50 in-payload iterations averaged 6,912,169 cycles (~19.2 ms) under PSRAM-XIP ([exp_r4-bench_20261016_172030.log](./logs/exp_r4-bench_20261016_172030.log)).
  - Binary footprint: Vendored `libsecp256k1` requires ~49.4 KB; mbedTLS P-256 requires ~33 KB (already linked).
- **Verdict: KEEP secp256k1.** Although P-256 is ~24% faster, verification time (~25 ms) is negligible compared to multi-second SD card reads and flash hashing. secp256k1 is the standard of the Bitcoin hardware wallet ecosystem, enabling direct multisig release signing from air-gapped devices.

---

### R5: Alternate Handoff & Execution Paths

- **Hypothesis:** Payloads that fit entirely within internal SRAM do not require Cache MMU reprogramming, allowing a simpler, robust execution handoff.
- **Implementation:**
  - **R5a (Pure Internal SRAM):** Created [hello_sram](./test_payloads/hello_sram/), compiled with `APP_BUILD_TYPE_RAM=y` and `APP_BUILD_TYPE_PURE_RAM_APP=y`. Binary image has 0 external segments.
  - **R5c (no-JMP Candidate):** Patch [r5-nojmp.patch](./loader_changes/r5-nojmp.patch) removes Cache MMU programming and cache eviction loops, executing direct copies and jumping, but refusing XIP payloads fail-closed.
  - **R5b (LP-Core Assist):** Architectural study of delegating segment copy to the low-power RISC-V core.
- **Physical Silicon Results:**
  - R5a under production loader: Loader detects zero external footprint (`PSRAM MMU footprint: 0 bytes`), copies 4 internal segments, and executes the payload. Interactive REPL functions cleanly (`ping -> PONG`) ([exp_r5-sram-interact_20261016_181659.log](./logs/exp_r5-sram-interact_20261016_181659.log)).
  - R5c with `hello_sram`: Boots successfully with MMU mapping skipped ([r5_nojmp_sram.log](./logs/r5_nojmp_sram.log)).
  - R5c with XIP payload: Refuses execution cleanly: `R5c REFUSED: payload needs MMU mappings` -> `HALT` ([r5_nojmp_xip.log](./logs/r5_nojmp_xip.log)).
  - R5b adjudication: Rejected at design. Copying 100 KB takes microseconds; inter-core synchronization overhead and expanded attack surface yield negative engineering value.
- **Verdict: ADOPT zero-mapping fallback; ADOPT fail-closed refusal rules; REJECT LP-core assist.**

---

### R6: Power-Tear & TOCTOU Race Immunity

- **Hypothesis:** SD card streaming and firmware updates are immune to mid-stream power cuts and cannot be coerced into booting partially written bundles.
- **Implementation:**
  - Mid-stream tear simulation: [tear_upload.py](./tools/tear_upload.py) streams an SD upload and abruptly terminates the connection via `SIGKILL` at 54.5% completion without committing.
  - Power-loss during boot: Physical resets injected at 1s, 3s, and 6s after power-on.
  - Double-read comparison: Patch [r6-double-read.patch](./loader_changes/r6-double-read.patch) performs two consecutive reads of the entire bundle and verifies they are byte-identical.
- **Physical Silicon Results:**
  - Torn upload ([r6_tear1.log](./logs/r6_tear1.log)): Next boot halts cleanly: `Firmware file /sdcard/seedsigner_esp32p4.bin not found. Halting.` The staging protocol relies on temporary filenames and atomic renames, preventing incomplete binaries from ever being visible.
  - Mid-boot resets ([r6_tear_boot1.log](./logs/r6_tear_boot1.log), [r6_tear_boot3.log](./logs/r6_tear_boot3.log), [r6_tear_boot6.log](./logs/r6_tear_boot6.log)): 3 out of 3 resets reboot cleanly. Bootloader execution is fully idempotent.
  - Double-read overhead ([r6_dr_good.log](./logs/r6_dr_good.log)): Added 90 ms of boot latency for a 196 KB payload (~2-3% of boot time).
- **Verdict: KEEP single-read default.** Atomic staging and immediate unmount prior to verification completely eliminate the TOCTOU window by construction. Double-read remains an optional hardening toggle.

---

### R7: Encrypted Bundle Assessment

- **Hypothesis:** Symmetric AEAD encryption (IETF ChaCha20-Poly1305) over payload bundles can provide firmware confidentiality within the stateless boot timing budget.
- **Implementation:** The test payload was augmented with `bench_aead` using mbedTLS. It executes authenticated encryption and decryption over a 128 KB deterministic buffer in PSRAM heap. Host tool [verify_r7.py](./tools/verify_r7.py) independently verifies cryptographic compliance.
- **Physical Silicon Results:**
  - Encryption: 16,489,811 cycles (~45.8 ms) -> ~2.8 MB/s throughput ([exp_r7-aead_20261016_190309.log](./logs/exp_r7-aead_20261016_190309.log)).
  - Decryption: 16,116,598 cycles (~44.8 ms) -> ~2.8 MB/s throughput.
  - Tamper rejection: Modifying one byte of authentication tag causes immediate failure (`MBEDTLS_ERR_CHACHAPOLY_AUTH_FAILED`, error code -86).
  - Host interop: Host tool verifies identical ciphertext SHA-256 and authentication tag.
- **Verdict: DEFER deployment, RETAIN benchmarks.** SeedSigner firmware is fully open source; encrypting public binaries provides no threat-model protection while adding substantial key-management overhead.

---

### R8: Physical Readout Audit (ROM Download Stub Extraction)

- **Hypothesis:** An adversary with 30 seconds of physical custody and a USB cable can extract entire flash contents via the ROM download stub. Auditing extracted dumps verifies that zero chain-breaking secrets exist in plaintext.
- **Implementation:** Executed 7 `read_flash` operations across all physical flash regions without altering chip configuration ([exp_r8-alive_20261016_190624.log](./logs/exp_r8-alive_20261016_190624.log)).
- **Physical Silicon Results:**
  - Readout capability: Flash memory has no hardware readout protection enabled; bootloader (120 KB), partition table, NVS (24 KB), virtual eFuse store (8 KB), and factory app (2 MB) read out cleanly.
  - Secret analysis:
    - Vendor public keys are present in plaintext (public by design).
    - Private signing keys are completely absent across all dumps.
    - Secure Boot V2 RSA private key appears nowhere; only the public key digest (`ba46ae3f...529fc933`) is present in the virtual eFuse store, byte-matching host calculations.
    - `random_fill` partitions exhibit true random entropy (50.0% bit distribution).
- **Verdict: BASELINED.** The stateless bootloader architecture stores zero runtime secrets in flash. Physical extraction yields no private keys. Hardware readout protection (`DIS_DOWNLOAD_MODE`, JTAG disable, and flash encryption) will be finalized during Phase 24 lockdown.

---

## 5. Decision Matrix & Downstream Inheritance

| Route | Topic | Silicon Verdict | Downstream Roadmap Inheritance |
|---|---|---|---|
| **R0** | Scrub-After-Use Discipline | **ADOPT (Proven Oct 16, 2026)** | All payloads processing private keys must zeroize secrets immediately after use; survives hardware resets. |
| **R1** | Software-Only Verified Boot | **CONFIRMED (Oct 16, 2026)** | Layer 2 alone provides complete SD tamper protection; flash-loader authenticity strictly requires Layer 1 (Phase 24). |
| **R2** | Reversible Anti-Rollback | **REVERSIBLE-ONLY (Oct 16, 2026)** | Useful as secondary protection; production anti-rollback strictly requires hardware `SECURE_VERSION` eFuses (Phase 24). |
| **R3** | Software-Bound Anti-Phishing | **REVERSIBLE-ONLY (Oct 16, 2026)** | Board/card binding proven; production unforgeability strictly requires permanent HMAC KEY5 burns (Phase 24). |
| **R4** | Signature Schemes & Thresholds | **KEEP secp256k1 (Oct 16, 2026)** | Maintain secp256k1 for Bitcoin hardware wallet multisig integration; multi-key overhead is minimal (~10 ms/sig). |
| **R5** | Alternate Handoff & Execution Paths | **ADOPT Fallback (Oct 16, 2026)** | Support zero-mapping internal SRAM payloads; enforce fail-closed refusal on fast paths; reject LP-core assist. |
| **R6** | Power-Tear & TOCTOU Immunity | **KEEP Single-Read (Oct 16, 2026)** | Atomic staging and immediate unmount guarantee race immunity; double-read maintained as optional hardening toggle. |
| **R7** | Encrypted Bundle Evaluation | **DEFER (Oct 16, 2026)** | Open-source firmware requires no confidentiality; benchmark figures (~2.8 MB/s) preserved for future reference. |
| **R8** | Physical Readout Audit | **BASELINED (Oct 16, 2026)** | Verified zero chain-breaking secrets reside in flash; permanent lockdown deferred to Phase 24. |

---

## 6. Limits & Deferred Production Features

To ensure complete clarity regarding production readiness:

1. **Physical eFuse Provisioning Deferred:** Permanent burns of HMAC KEY5, `SECURE_VERSION` anti-rollback counters, `DIS_DOWNLOAD_MODE`, and JTAG disable registers are deferred to Phase 24.
2. **Flash Encryption:** Hardware flash encryption and external PSRAM encryption bypass (`SPIRAM_ENC_EXEMPT`) remain deferred pending ESP-IDF v6.x upstream stabilization.
3. **Display and Camera Contention:** Peripheral bus contention (MIPI-DSI, ISP, and DMA) under full SeedSigner application workload is evaluated in Phase 23.
4. **Platform Portability:** Results are validated on ESP32-P4 v1.3 silicon. The ESP32-S3 implementation remains frozen at Phase 17 semantics until Phase 27.

---

## 7. Deliverable Artifacts & Test Runbook

### Artifact Catalog

- **Patches ([loader_changes/](./loader_changes/)):** Lossless patches against mainline bootloader (`r2-rollback.patch`, `r3-salt-bind.patch`, `r4-verify-bench.patch`, `r5-nojmp.patch`, `r6-double-read.patch`).
- **Test Payloads ([test_payloads/](./test_payloads/)):** Standalone test payload projects ([canary_scrub_r0/](./test_payloads/canary_scrub_r0/) and [hello_sram/](./test_payloads/hello_sram/)).
- **Host Tools ([tools/](./tools/)):** Verification and attack generation scripts ([verify_r3.py](./tools/verify_r3.py), [verify_r7.py](./tools/verify_r7.py), [make_attacks.py](./tools/make_attacks.py), [sign_multisig.py](./tools/sign_multisig.py), [tear_upload.py](./tools/tear_upload.py)).
- **Execution Logs ([logs/](./logs/)):** 50+ raw UART console logs covering CONTROL and PATCHED pairs across all routes.

### Reproduction Runbook

#### 1. Validate Cryptographic Interop (R7)
```bash
python3 tools/verify_r7.py --bench-log ./logs/exp_r7-aead_20261016_190309.log
```
*Expected output: `R7 VERIFY: MATCH (interop proven)`*

#### 2. Validate Software-Bound Anti-Phishing Derivation (R3)
```bash
python3 tools/verify_r3.py --boot-log ./logs/r3_bootA_saltA.log
```
*Expected output: `R3 VERIFY: MATCH`*

#### 3. Build and Test Pure-SRAM Payload (R5a)
```bash
source ~/esp/esp-idf-v5.5/export.sh
cd test_payloads/hello_sram
idf.py set-target esp32p4
idf.py build
python3 -m esptool --chip esp32p4 elf2image \
  --flash_mode dio --flash_freq 80m --flash_size 16MB \
  -o build/hello_sram.bin build/hello_sram.elf
```
Wrap and upload to microSD; bootloader will execute with zero MMU allocations.
