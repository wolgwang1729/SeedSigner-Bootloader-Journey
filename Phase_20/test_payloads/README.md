# Phase 20 Test Payloads

This directory contains standalone, C-only test payloads used across the Phase 20 alternate secure routes evaluation. Each payload compiles independently with ESP-IDF v5.5, targets the ESP32-P4 v1.3 silicon, and wraps into a signed Specter binary.

## Payload Catalog

| Payload Directory | Route Focus | Description |
|---|---|---|
| `canary_scrub_r0/` | R0, R1, R2, R4, R7 | Extended memory canary payload featuring crash hooks, `use_and_scrub` lifecycle zeroization, `wipe_rb` rollback sector erasure, `bench_p256` ECDSA verification, and `bench_aead` ChaCha20-Poly1305 benchmarking. |
| `hello_sram/` | R5a, R5c | Pure internal-SRAM payload built without SPIRAM XIP mappings. Exercises the zero-mapping loader handoff path with direct internal SRAM copies and an interactive serial REPL (`ping`, `info`). |

## Directory Organization

- `canary_scrub_r0/`: See [canary_scrub_r0/README.md](./canary_scrub_r0/README.md) for build, signing, and canary memory map details.
- `hello_sram/`: See [hello_sram/README.md](./hello_sram/README.md) for RAM-loadable build instructions and verification procedure.
