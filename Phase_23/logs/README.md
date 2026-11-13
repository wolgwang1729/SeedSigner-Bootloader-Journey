# Phase 23 - Execution Logs

This directory contains execution traces and logs proving stateless SeedSigner application boot and Bitcoin PSBT signing across both emulated and physical hardware targets.

## Log Files

| File | Target & Environment | Architecture | Execution Summary |
|---|---|---|---|
| `p4_emu_stateless_sign.txt` | ESP32-P4 (`esp-emu` v0.50.0) | RISC-V RV32IMAFCP | Pre-silicon headless execution: SB V2 -> secp256k1 multisig -> Cache MMU remap -> MicroPython app boot -> 3-input SegWit PSBT signed in 288 ms with 14.99 MB free PSRAM heap. Verified by `verify_signed_psbt.py`. |
| `p4_hw_stateless_sign.txt` | ESP32-P4 (Physical DevKit v1.3) | RISC-V RV32IMAFCP | Silicon execution: bundle uploaded to microSD over UART via RAM uploader (`sd_upload.py`). Booted through SB V2 (virtual eFuses) + multisig; verified anti-phishing proof (`wonder echo bomb balcony`); 3-input PSBT signed in 631 ms with 14.99 MB free PSRAM heap; 2 UR frames exported. Consensus-verified against `testqrs.com`. |
| `s3_emu_stateless_sign.txt` | ESP32-S3 (`esp-emu` v0.50.0) | Xtensa LX7 | First execution of genuine SeedSigner stack on S3 stateless bootloader: 3-input PSBT signed in 570 ms with 4.91 MB free PSRAM heap. Consensus-verified against `testqrs.com`. |

## Verification

All three logs can be independently verified on the host against Bitcoin consensus rules and sighash matching:

```sh
python3 Phase_23/tools/verify_signed_psbt.py Phase_23/logs/p4_emu_stateless_sign.txt
python3 Phase_23/tools/verify_signed_psbt.py Phase_23/logs/p4_hw_stateless_sign.txt
python3 Phase_23/tools/verify_signed_psbt.py Phase_23/logs/s3_emu_stateless_sign.txt
```
