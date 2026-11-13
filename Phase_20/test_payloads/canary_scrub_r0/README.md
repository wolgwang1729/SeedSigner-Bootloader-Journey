# canary_scrub_r0 - Phase 20 Extended Test Payload

`canary_scrub_r0` extends the Phase 19 canary payload with commands for evaluating multiple Phase 20 routes (R0 scrub-after-use, R2 rollback wipe, R4 P-256 microbenchmark, and R7 AEAD benchmark).

## Extended Commands

- `use_and_scrub`: Plants mock secret in PSRAM (1 MB) and SRAM (4 KB), folds its content into an observable sink via DJB hash, immediately zeroizes memory, and verifies zeros live (`USED_AND_SCRUBBED ok=1`). Verifies that following `fault_hpwdt` resets report `CANARY_CLEARED` on reboot, closing the hardware watchdog physics gap.
- `wipe_rb`: Erases the 4 KB NVS rollback counter sector at flash offset `0x1000` to verify that rollback refusal is reversible.
- `bench_p256`: Runs 50 iterations of P-256 ECDSA verification over PSRAM-XIP, measures execution cycles, and verifies negative test rejection.
- `bench_aead`: Runs 128 KB ChaCha20-Poly1305 encryption and decryption, printing the ciphertext SHA-256 and 16-byte authentication tag for host verification.

## Build Instructions (ESP-IDF v5.5)

```bash
source ~/esp/esp-idf-v5.5/export.sh
cd test_payloads/canary_scrub_r0
idf.py set-target esp32p4
idf.py build
```

## Sign-Time Canary-Overlap Check

The mock secret canary lives at fixed address `0x48400000` (4 MB into the PSRAM window). The payload bundle must terminate below this threshold:

```bash
python3 ../../tools/check_canary_overlap.py \
  --target esp32p4 \
  build/canary_scrub.bin
```

## Sign and Wrap into Specter Bundle

```bash
python3 ../../tools/sign_multisig.py \
  --key ../keys/r4_throwaway_1.pem \
  --platform seedsigner_esp32p4 \
  --version 1 \
  build/canary_scrub.bin build/canary_r0_esp32p4.bin
```

## Memory Layout (ESP32-P4)

| Region | Address Range | Description |
|---|---|---|
| PSRAM secret window | `0x48400000` to `0x484FFFFF` (1 MB) | Loader-inspected cross-reset proof |
| SRAM secret zone | `0x5010E000` to `0x5010EFFF` (4 KB) | Payload self-reported (`sram_nonzero`) |
| Telemetry words | `0x5010FFE0` | Fired indicator and cycle counts |
| Test magic word | `0x5010FFF0` | Loader inspector activation gate |

## Campaign Workflow

1. `selftest` -> `SELFTEST_OK` (verifies wipe loop and stack switch without resetting).
2. `scrub_off` -> `plant` -> `fault_restart` -> Next boot logs `CANARY_REMANENT` (positive control: retention confirmed).
3. `scrub_on` -> `plant` -> `fault_restart` -> Next boot logs `CANARY_CLEARED` (patched behavior: zeroization confirmed).
4. `plant` -> `fault_abort` and `plant` -> `fault_wdt` -> Confirm zeroization on abort and interrupt watchdog panics.
5. `plant` -> `fault_hpwdt` -> MWDT0 hardware reset retains canary (`CANARY_REMANENT`), demonstrating the hardware watchdog physics boundary.
6. `use_and_scrub` -> `fault_hpwdt` -> Confirms zeroization across hardware watchdog reset (`CANARY_CLEARED`), proving use-time hygiene survives hardware resets.
