# Phase 20 Silicon Execution Logs

This directory contains raw UART console logs captured directly from physical ESP32-P4 v1.3 silicon during the Phase 20 alternate secure routes campaign (October 16, 2026). Every route was evaluated using reversible operations only, maintaining virtual eFuses (`CONFIG_EFUSE_VIRTUAL=y`), with zero physical fuse modifications.

## Log Catalog by Route

### Route R0: Scrub-After-Use Discipline (MWDT Boundary Closure)
- `exp_r0-baseline_20261016_154448.log`: Initial baseline boot and self-test verification.
- `exp_r0-control_20261016_154603.log`: Control run (`scrub_off, plant, fault_restart`) confirming retention (`CANARY_REMANENT`).
- `exp_r0-patched_20261016_154702.log`: Patched run (`scrub_on, plant, fault_restart`) confirming crash sanitization (`CANARY_CLEARED`).
- `exp_r0-abort_20261016_154749.log`: Assertion failure crash test (`plant, fault_abort`) confirming zeroization (`CANARY_CLEARED`).
- `exp_r0-wdt_20261016_154834.log`: Interrupt watchdog timeout test (`plant, fault_wdt`) confirming zeroization (`CANARY_CLEARED`).
- `exp_r0-hpwdt_20261016_154916.log`: Hardware watchdog reset test (`plant, fault_hpwdt`) demonstrating hardware remanence without early scrub (`CANARY_REMANENT`).
- `exp_r0-use-and-scrub-v2_20261016_155905.log`: Scrub-after-use verification (`use_and_scrub, fault_hpwdt`) proving zeroization even across hardware resets (`CANARY_CLEARED`).

### Route R1: Software-Only Verified Boot (Layer 2 Isolation)
- `r1_good.log`: Valid bundle boot without Layer 1 Secure Boot V2 (Specter multisig PASSED, words displayed, successful JMP).
- `r1_raw.log`: Rejection of raw binary without Specter header.
- `r1_wrong-platform.log`: Rejection of bundle built for mismatched platform string (`seedsigner_esp32s3`).
- `r1_downgrade.log`: Rejection of bundle with payload version zero (`pl_ver=0`).
- `r1_tamper.log`: Rejection of bundle with single-bit payload tamper.
- `r1_badsig.log`: Rejection of bundle with tampered signature segment.
- `r1_restored.log`: Full flash restoration to production Secure Boot V2 state.

### Route R2: Reversible Monotonic Anti-Rollback
- `r2_v2.log`: Version 2 bundle boots and advances NVS counter (`1 -> 2`).
- `r2_v1_refused.log`: Version 1 bundle rejected by NVS counter check (`pl_ver=1 < stored=2`).
- `exp_r2-wipe-rb_20261016_163047.log`: Test payload command `wipe_rb` erasing rollback NVS sector.
- `r2_v1_after_wipe.log`: Version 1 bundle boots successfully after NVS erase, confirming reversible behavior.
- `r2_restored.log`: Flash restoration and verification.

### Route R3: Software-Bound Anti-Phishing Words
- `r3_bootA_saltA.log`: First boot with salt auto-provisioning, logging salt ID, SD CID pack, and initial BIP-39 words.
- `r3_bootA_stable.log`: Reboot verifying words remain stable without reprovisioning.
- `r3_bootB_saltB.log`: Host erase of salt sector leading to fresh salt generation and distinct words.
- `r3_tamper.log`: Single-bit flip in `random_fill` triggering fail-closed hash mismatch halt.
- `r3_reprovision_wordsC.log`: Flash re-fill and salt recovery producing fresh consistent words.
- `r3_restored.log`: Flash restoration to baseline anti-phishing state.

### Route R4: Signature Scheme & Threshold Evaluation
- `r4_2of2.log`: Evaluation of 2-of-2 secp256k1 multisig verification timing (~35.4 ms).
- `r4_1of2.log`: Single signature presented under 2-of-2 threshold, verifying fail-closed halt.
- `exp_r4-bench_20261016_172030.log`: In-payload microbenchmark of P-256 ECDSA verification (~19.2 ms).
- `r4_restored.log`: Restoration to production threshold keys.

### Route R5: Alternate Handoff & Execution Paths
- `r5_sram_unmodified_loader.log`: Pure internal-SRAM payload (`hello_sram`) booting unmodified loader with zero MMU mappings.
- `exp_r5-sram-interact_20261016_181659.log`: Interactive serial REPL session (`ping -> PONG`, `info`).
- `r5_nojmp_sram.log`: no-JMP loader candidate booting `hello_sram` successfully.
- `r5_nojmp_xip.log`: no-JMP loader candidate refusing XIP payload fail-closed.
- `r5_nojmp_bad.log`: no-JMP loader rejecting corrupted bundle fail-closed before handoff.
- `r5_restored.log`: Production loader restoration.

### Route R6: Power-Tear & TOCTOU Immunity
- `r6_tear1.log`: Uploader terminated mid-stream at 54.5% transfer; next boot halts cleanly with file not found.
- `r6_tear_boot1.log`, `r6_tear_boot3.log`, `r6_tear_boot6.log`: Mid-boot power cuts at 1s, 3s, and 6s booting cleanly on restart.
- `r6_dr_good.log`: Double-read loader reading and matching both passes (+90 ms overhead).
- `r6_dr_bad.log`: Double-read loader rejecting corrupt file during signature verification.
- `r6_restored.log`: Production loader restoration.

### Route R7: Encrypted Bundle Assessment
- `exp_r7-aead_20261016_190309.log`: In-payload ChaCha20-Poly1305 AEAD throughput and auth-tag verification.

### Route R8: Physical Readout Audit
- `exp_r8-alive_20261016_190624.log`: ROM download stub extraction audit and hash verification.
