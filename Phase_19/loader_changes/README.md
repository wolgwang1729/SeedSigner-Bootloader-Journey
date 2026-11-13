# Phase 19 - bootloader-side changes (moved off the feature branch)

Per repo convention, all Phase 19 work product that lived on
the `phase19-sanitization-glitch` branch of `seedsigner-esp32-bootloader` is
archived here. That branch has been deleted; the bootloader repo is back to
pristine `main`.

## Lossless record

`phase19-sanitization-glitch.patch` - full `git diff` of the branch vs
`main` (19 files, +1431/-59; includes the 1 MB widening: chunked inspector,
`CANARY_LEN`, host-test update). Verified with `git apply --check` against
pristine `main`. To restore the branch:

```bash
cd seedsigner-esp32-bootloader
git checkout -b phase19-sanitization-glitch
git apply <path-to-phase-19>/loader_changes/phase19-sanitization-glitch.patch
```

## Post-close extension - power-cycle canary (Oct 19, 2026)

The cold power-cycle retention check was built on a second short-lived
branch `phase19-power-canary`, stacked on the state above (branch commit
`e9ad09c` = pristine `main` + `phase19-sanitization-glitch.patch`). Also
deleted after archiving. `phase19-power-canary.patch` - `git diff` vs that
stacked base (1 file: `main/main.c`, +55/-8). Adds:

- unconditional inspect branch on `ESP_RST_POWERON` / `ESP_RST_BROWNOUT` (the
  warm RTC-magic gate dies with the rail, so cold boots could never inspect);
- 2 s capture settle before the cold print + `reason=<cause>` in the verdict;
- exact `pattern matches=N/262144` counter against `p[i] = CANARY_PATTERN32 ^ i`.

Test build only - production loader paths untouched. To restore (apply order
matters):

```bash
cd seedsigner-esp32-bootloader
git checkout -b phase19-power-canary
git apply <path-to-phase-19>/loader_changes/phase19-sanitization-glitch.patch
git add -A && git commit -m "phase19 canary rig (stacked base)"
git apply <path-to-phase-19>/loader_changes/phase19-power-canary.patch
```

Rig driver: `../tools/power_canary_check.py`. Results: `../logs/powercycle_*`.

## File map (paths relative to the bootloader repo root)

New files (also copied next to this folder, mirrored at exact repo paths):

| Repo path | Copy here |
|---|---|
| `test_payloads/canary_scrub/` (payload sources; `build/` + generated `sdkconfig` excluded) | `../test_payloads/canary_scrub/` |
| `tools/check_canary_overlap.py` | `../tools/check_canary_overlap.py` |
| `host_test/tests/test_secure_status.cpp` | `../host_test/tests/test_secure_status.cpp` |
| `conftest.py` (`--canary` pytest gate) | `../conftest.py` |

Modified files (in the patch only, not copied - they are bootloader-owned):

| File | Change |
|---|---|
| `main/main.c` | G2 early canary inspector (pre-SD-load) + G3 double-branch/`SECURE_OK/FAIL`/jitter + G4 `halt_and_scrub` |
| `main/bundle_validate.h` | `secure_status_t`, `bundle_status_from_*`, `secure_check_double` |
| `main/loader_config.h` | `SECURE_OK/FAIL`, jitter bounds, `CANARY_PADDR/LEN`, `RTC_TEST_MAGIC` |
| `main/esp_image.c` | Fatal paths scrub `fake_flash` + plan |
| `sdkconfig.defaults` | `CONFIG_SPIRAM_MEMTEST=n` (memtest destroys canary evidence) |
| `host_test/Makefile`, `host_test/README.md` | New test wiring + docs |
| `pytest_seedsigner_bootloader_p4_stateless_os.py` | `test_canary_scrub_campaign` (`--canary`-gated) |
| `docs/security_analysis.md` | Phase 19 appendix + silicon results |

## Board logs

`../logs/` - raw UART captures: `campaign_control_patched.txt`
(scrub_off -> REMANENT, scrub_on -> CLEARED via `fault_restart`),
`campaign_abort_wdt.txt` (`CLEARED` via `fault_abort` + `fault_wdt`),
`campaign_hpwdt.txt` (`REMANENT` via `fault_hpwdt`, MWDT system reset),
`campaign_wide_1mb.txt` (1 MB + SRAM selftest/control/patched + timing),
`campaign_wide_abort.txt` (`CLEARED` via `fault_abort`, noreturn path),
`boot_canary.txt` (full loader -> shim -> payload boot),
`powercycle_session.txt` (+ `.raw`) - cold power-cycle campaign (full
capture; two physical power cuts), `powercycle_summary.txt` - the per-cycle
evidence lines extracted from it.
