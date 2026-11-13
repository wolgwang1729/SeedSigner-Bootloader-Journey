# canary_scrub - Phase 19 G1 test payload

C-only signed test payload: plants a fixed PSRAM canary, installs
panic/WDT scrub hooks, and faults on UART command. The loader's early
inspector reports `CANARY_REMANENT` (control) vs `CANARY_CLEARED`
(patched) on the next boot.

## Build (P4)

```bash
source ~/esp/esp-idf-v5.5/export.sh
cd test_payloads/canary_scrub
idf.py set-target esp32p4
idf.py build
```

Raw app image: `build/canary_scrub.bin` (the factory app image `idf.py build`
produces).

## Sign-time canary-overlap assert (manual, required)

The canary lives at fixed `CANARY_PADDR` (P4 `0x48400000` = 4 MB into the
PSRAM window). The signed bundle + staged image must end below it:

```bash
python3 tools/check_canary_overlap.py \
  --target esp32p4 \
  build/canary_scrub.bin
```

Fails the build if the raw image is >= 4 MB (would overlap the canary).
Current payload is ~200 KB - comfortably clear.

## Sign

```bash
# Reuse the current pl_ver (do NOT consume future SECURE_VERSION budget).
python3 ../../tools/generate_signed_payload.py \
  --platform seedsigner_esp32p4 \
  --version 1 \
  build/canary_scrub.bin canary_esp32p4.bin
```

Copy `canary_esp32p4.bin` to the SD card as `seedsigner_esp32p4.bin`:

```bash
./run.sh --target esp32p4 upload-sd canary_esp32p4.bin --name seedsigner_esp32p4.bin
```

## Memory layout (P4 - non-overlap is load-bearing, see F-overlap)

| Region | Address | Notes |
|---|---|---|
| PSRAM secret window | `0x48400000-0x484FFFFF` (1 MB) | loader-inspected cross-reset proof |
| SRAM secret | `0x5010E000-0x5010EFFF` (4 KB) | payload self-reported (`sram_nonzero`) |
| Telemetry | `0x5010FFE0` (fired, cycles) | fixed words, empirically stable |
| Test magic | `0x5010FFF0` (1 word) | loader inspector gate |

## Campaign

1. `selftest` -> `SELFTEST_OK` (live proof of the wipe loop + stack-switch
   mechanism, no reset involved).
2. `scrub_off` -> `plant` -> `fault_restart` -> next boot logs
   `CANARY_REMANENT` (positive control - retention proven, 1 MB PSRAM +
   4 KB SRAM secret both patterned).
3. `scrub_on` -> `plant` -> `fault_restart` -> next boot logs
   `CANARY_CLEARED` (payload also self-reports `sram[0]=0` + scrub cycles).
4. Repeat with `fault_abort` and `fault_wdt`; record which hook fired
   (`[canary] last scrub fired, cycles=N` on the following payload boot).
5. Boundary: `scrub_on` -> `plant` -> `fault_hpwdt` (MWDT0 system reset, no
   software runs) -> next boot must log `CANARY_REMANENT` with a WDT-family
   reset cause - proving hardware resets bypass scrubbing by physics.
   HP_SYS_WDT hardware resets may bypass both hooks - documented as a
   limitation (see Phase 19).
6. **Power-cycle (cold-boot) check** - Oct 19 verification, needs the test-build
   loader extension (`loader_changes/phase19-power-canary.patch`): `scrub_off`
   -> `plant` -> `fault_restart` -> confirm `pattern matches=262144/262144` on
   the next boot (physical proof) -> cut devkit power -> the next boot's
   un-gated cold inspect must report `pattern matches=0/262144` (nothing
   retained). The match counter is computed by the loader against
   `p[i] = 0xCA4A5EED ^ i`, so it needs no payload cooperation. Details:
   Phase 19.

No eFuse action. No display. Mock pattern only - never a real seed.
