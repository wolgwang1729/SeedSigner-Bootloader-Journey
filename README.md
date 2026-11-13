# SeedSigner Stateless Secure Bootloader — Engineering Journey

**Author:** Mayank Yadav ([@wolgwang](https://github.com/wolgwang1729))  
**Project:** Stateless Secure Boot & Air-Gapped Firmware Architecture for ESP32 (ESP32-P4 & ESP32-S3)  
**Ecosystem:** SeedSigner, Specter-DIY, Kern  
**Origins:** Initiated via Summer of Bitcoin 2026 & Continued via Bitshala Fellowship  

---

## Overview

SeedSigner established that an air-gapped, stateless Bitcoin signing device built from commodity hardware eliminates reliance on proprietary hardware wallet vendors. However, traditional Single Board Computers (such as the Raspberry Pi Zero) introduce notable drawbacks: general-purpose Linux OS attack surfaces, 45-second boot times, high power draw, and persistent supply chain bottlenecks.

This repository documents the complete **Engineering & Research Journey** of designing, prototyping, and production-hardening a stateless secure bootloader for low-cost ($15–$20), instant-booting microcontrollers (**ESP32-P4** and **ESP32-S3**) while upholding SeedSigner's core tenet: **absolute statelessness**.

---

## The Architectural Challenge: Microcontrollers vs. Statelessness

Commodity microcontrollers natively execute firmware in-place (XIP) directly from onboard SPI flash. Flashing a Bitcoin signing device's firmware to persistent internal storage introduces severe security risks:

* **Evil-Maid Flash Tampering:** An attacker with temporary physical access can modify flash partitions to compromise signing logic, weaken random number generators, or exfiltrate private key entropy.
* **Secret Persistence:** Flash wear-leveling and unallocated sectors make it easy for rogue code or buggy libraries to stash private keys, xpubs, or seed entropy across reboots.
* **Supply Chain Vulnerability:** Pre-flashed devices cannot be independently verified with the same confidence as an ephemeral SD card image.

---

## The Solution: Hybrid Stateless Architecture

To resolve this conflict, this project implements a two-layer hybrid architecture that delivers both silicon-enforced security and 100% volatile execution:

```
[ Removable FAT32 SD Card ]
            │
            ▼ (Atomic Read & Immediate Unmount — Anti-TOCTOU)
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Hardware Root of Trust                                 │
│ • ESP-IDF Secure Boot V2 (RSA-3072 / ECDSA-P256)                │
│ • Cryptographically bound to silicon eFuses                     │
│ • Validates immutable 2nd-stage bootloader in flash             │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Stateless Loader & secp256k1 Multisig                  │
│ • Validates SD bundle via Bitcoin-native secp256k1 multisig     │
│ • Anti-phishing TRNG proof (BIP-39 visual canary on boot)       │
│ • Cache MMU Hijack: remaps PSRAM physical pages to IROM/DROM   │
│   (0x48000000 on P4 / 0x42000000 on S3)                         │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼ (In-Memory Execution Only)
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Runtime Execution & Panic Sanitization                 │
│ • Firmware runs entirely from volatile PSRAM                    │
│ • Zero payload bytes ever written to flash                      │
│ • Panic/WDT zeroization scrubbers prevent cold-boot remanence   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Hardware Demos

| Target | Board | PSRAM | Signature Scheme | Demo Link |
|---|---|---|---|---|
| **ESP32-P4** | Waveshare ESP32-P4 WiFi6 Touch LCD 4.3 | 32 MB | RSA-3072 + secp256k1 Multisig | [Watch P4 Demo Video](https://www.youtube.com/watch?v=jkk55UFmpCI) |
| **ESP32-S3** | Waveshare ESP32-S3-Touch-LCD-3.5B / DEV-KIT | 8 MB Octal | RSA-3072 + secp256k1 Multisig | [Watch S3 Demo Video](https://www.youtube.com/watch?v=al7gvf-3Q34) |

---

## Repository Structure & Engineering Phases

The complete R&D progression is thoroughly documented and divided into 23 chronological phases:

* **[`LiteratureReview.MD`](./LiteratureReview.MD):** Deep architectural analysis of the Specter-DIY bootloader, ESP-IDF internals, and Kern design.

### Chronological Phases
* **[Phase 1: Minimal Secure Boot Prototype](./Phase_01/Phase_1_Prototype.md)**  
  Setting up ESP-IDF and enabling Secure Boot v2 on ESP32-S3 QEMU. Demonstrates Trust-On-First-Use (TOFU) eFuse burning and attack failure modes.
* **[Phase 2: SD Card Boot & Stateless Execution](./Phase_02/Phase_2_SD_Card_Boot.md)**  
  Development of the App-Based Secure Loader. Implements anti-TOCTOU SD card logic, `secp256k1` signature verification, and the Cache MMU Hijack technique to route instruction fetches to PSRAM.
* **[Phase 3: Hardware Secure Boot Integration](./Phase_03/Phase_3_Hardware_Secure_Boot.md)**  
  Merging Layer 1 (Secure Boot v2) and Layer 2 (App-Based Loader) into a complete, emulated end-to-end boot flow.
* **[Phase 4: Loading SeedSigner Firmware](./Phase_04/Phase_4_Loading_SeedSigner_Firmware.md)**  
  Adapting the bootloader pipeline to load MicroPython payloads. Resolving IRAM/DRAM access violations, hidden MMU misalignments, and stack self-overwrite bugs.
* **[Phase 5: Environment Upgrade & MicroPython Execution](./Phase_05/Phase_5_Environment_Upgrade_and_MicroPython_Execution.md)**  
  Upgrading to modern ESP-IDF toolchains and booting official MicroPython builds for the ESP32-S3 via the stateless Secure Loader.
* **[Phase 6: UI Emulation & Validation via Wokwi](./Phase_06/Phase_6_UI_Emulation_and_Validation_via_Wokwi.md)**  
  Visually verifying the SeedSigner UI using Wokwi virtual hardware emulation, booting MicroPython to a fully interactive REPL prompt.
* **[Phase 7: Flash Hardening & Threat Analysis](./Phase_07/Phase_7_Flash_Hardening.md)**  
  Threat analysis of the stateless boot path on the ESP32-S3: seed stashing in flash, brute-force attacks, and the flash-fill mitigation.
* **[Phase 8: Hardware Bring-up (ESP32-S3)](./Phase_08/Phase_8_Hardware_Bring_up.md)**  
  Moving the secure loader off emulation onto real physical ESP32-S3 silicon: hardware bring-up, virtual eFuse secure-boot testing, and validation of the stateless handoff on hardware.
* **[Phase 9: ESP32-P4 Bring-up](./Phase_09/Phase_9_ESP32P4_Bring_up.md)**  
  Porting the loader to the dual-core RISC-V ESP32-P4. Navigating RISC-V boot flow, P4 cache/MMU differences, and Waveshare P4 board bring-up.
* **[Phase 10: ESP32-P4 PSRAM Handoff](./Phase_10/Phase_10_ESP32P4_PSRAM_Handoff.md)**  
  First stateless handoff on the ESP32-P4: Cache MMU remap of IROM/DROM to PSRAM physical pages, eviction ordering, and executing code out of volatile RAM.
* **[Phase 11: MicroPython on App Loader](./Phase_11/Phase_11_MicroPython_on_App_Loader.md)**  
  Booting the official MicroPython build statelessly through the P4 loader. Introduces the reusable `stateless_shim` and the CLIC vector-table fix required for RISC-V interrupts.
* **[Phase 12: Specter Secure App Loader on Stateless Boot](./Phase_12/Phase_12_Specter_Secure_App_Loader_on_Stateless_Boot.md)**  
  Loading firmware from a FAT32 SD card in the Specter `bl_section_t` bundle format with secp256k1 multisig verification, plus build/signing tooling for wrapping payloads.
* **[Phase 13: Secure Bootloader Hardening](./Phase_13/Phase_13_Secure_Bootloader_Hardening.md)**  
  Anti-phishing hardening of the loader: TRNG flash-fill of a dedicated ~6.8 MB partition hashed into BIP-39 visual proof words on boot, plus a production hardening plan (HMAC eFuse binding, anti-rollback, encryption).
* **[Phase 14: Security Analysis](./Phase_14/Phase_14_Security_Analysis.md)**  
  Master security analysis of the Phase 13 chain on the ESP32-P4: threat model, 12 attack scenarios (A1–A12), 8 discarded attack vectors (D1–D8), and a 16-test physical silicon verification campaign (T1–T16).
* **[Phase 15: ESP32-S3 Stateless Secure Loader Port](./Phase_15/Phase_15_ESP32S3_Stateless_Loader.md)**  
  Porting the stateless secure loader to the Xtensa ESP32-S3: IRAM JMP zone (`0x403A0000`), shared I/D MMU table (`0x600C5000`), fixed static RAM heap budgeting, and hardware verification.
* **[Phase 16: MicroPython on ESP32-S3 Stateless Boot](./Phase_16/Phase_16_ESP32S3_MicroPython_Stateless.md)**  
  Porting the SeedSigner MicroPython runtime to the ESP32-S3 stateless loader: Xtensa windowed ABI setup (`entry.S`), 5 MB PSRAM heap injection, REPL stdin/stdout wrapping, and interactive hardware REPL validation.
* **[Phase 17: ESP32-S3 Pure SD Card Boot & Flash Hardening](./Phase_17/Phase_17_ESP32S3_SDCard_Stateless_Boot.md)**  
  Elimination of all temporary flash payload partitions, expansion of `random_fill` to **5.875 MB** for maximal TRNG anti-phishing proof (4 BIP-39 words), atomic SDMMC/SDSPI ingestion with immediate unmount (anti-TOCTOU), dual SDSPI/SDMMC host support, and hardware verification on real ESP32-S3 silicon.
* **[Phase 18: Peripheral Integration & Virtual Display Prototype](./Phase_18/Phase_18_Virtual_Display_DevKit.md)**  
  Headless virtual display and touch emulation subsystem (`board_common_virtual_fb`) on the ESP32-P4-WIFI6-DEV-KIT to validate stateless PSRAM execution and the SeedSigner UI interaction stack during display panel stock shortages. (Interim headless test; retired for real hardware).
* **[Phase 19: Runtime PSRAM Sanitization, Panic Zeroization & Glitch Resistance](./Phase_19/Phase_19_Runtime_Sanitization_Glitch.md)**  
  Hardening the loader and stateless payloads against cold-boot and warm-reset PSRAM remanence: canary scrub hooks on panic/abort/WDT (`CANARY_CLEARED`), RTC-magic gated inspection, glitch resistance, and silicon verification showing zero retention across cold power cycles.
* **[Phase 20: Reversible Security R&D & Alternate Boot Paths](./Phase_20/Phase_20_Reversible_Security_Alternate_Boot.md)**  
  De-risking production without permanent hardware burns (R0–R7 silicon-proven): software-only verified boot, reversible NVS-bound anti-rollback, salt + SD-CID bound anti-phishing, benchmarking P-256 vs secp256k1 signature verification, minimal no-JMP handoff, and power-tear resilience.
* **[Phase 21: Headless Boot Emulator Rig (esp-emu)](./Phase_21/Phase_21_Headless_Boot_Emulator.md)**  
  Establishing a complete software emulation test rig using `esp-emu` for both ESP32-S3 and ESP32-P4. Faithfully models Secure Boot v2 eFuse verification, MMU PSRAM remapping, and boots hello-world and stock MicroPython to interactive REPL in emulation.
* **[Phase 22: Cross-Project Bring-up (Kern & Specter-DIY)](./Phase_22/Phase_22_Kern_Specter_Bringup.md)**  
  Proving the stateless loader is firmware-agnostic by booting two independent Bitcoin hardware wallet stacks from signed SD bundles on physical ESP32-P4 hardware: Odudex's **Kern** (C / ESP-IDF v6.1) and **Specter-DIY** (MicroPython / sandman21vs P4 port).
* **[Phase 23: Full SeedSigner App Boot & Stateless Signing](./Phase_23/Phase_23_SeedSigner_App_Boot.md)**  
  Executing genuine SeedSigner Bitcoin PSBT transaction signing statelessly from PSRAM through the complete Secure Boot V2 chain: seed ingestion, BIP-39 mnemonic parsing, key derivation, and multi-input PSBT signing with UR export. Proven end-to-end on physical ESP32-P4 rev 1.3 silicon, ESP32-P4 `esp-emu`, and ESP32-S3 `esp-emu`.

---

## Testing & Hardware Environment

* **Targets:**
  * **ESP32-P4** (Waveshare ESP32-P4 WiFi6 Touch LCD 4.3 & Waveshare ESP32-P4-WIFI6-DEV-KIT v1.3 headless)
  * **ESP32-S3** (ESP32-S3-DEV-KIT-N8R8 / Waveshare S3 Touch LCD 3.5B)
* **Toolchains:** ESP-IDF v5.5 (`~/esp/esp-idf-v5.5`) and ESP-IDF v6.1 (`~/esp/esp-idf-v6.1`).
* **Software Emulation:** `esp-emu` v0.50.0 (high-fidelity RISC-V ESP32-P4 & Xtensa ESP32-S3 emulation modeling hardware MMU and Secure Boot v2 eFuses).
* **Virtual eFuses:** All Secure Boot v2 eFuse operations during R&D use virtual mode (`CONFIG_EFUSE_VIRTUAL=y` + `KEEP_IN_FLASH` in the `efuse` partition), enabling repeatable full-chain testing on physical silicon without irreversible hardware burning.

---

## Acknowledgments & Community

* **Hardware Support:** Huge thanks to the **SeedSigner** team for directly funding the development hardware (ESP32-P4 & ESP32-S3 development kits) that made physical hardware testing and verification possible.
* **Origins & Fellowship:** Originally initiated during **Summer of Bitcoin 2026**, this project continues as an active open-source initiative supported by the **Bitshala Fellowship**.
* **Ecosystem Collaboration:** Deep gratitude to mentors and developers across the **SeedSigner**, **Specter-DIY**, and **Kern** open-source Bitcoin hardware ecosystems for ongoing technical feedback and collaboration.
