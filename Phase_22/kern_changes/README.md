# Phase 22 - Kern Stateless Changes

Apply on top of **Kern `7cdd258`** (C / ESP-IDF v6.1). The canonical form is the
patch; the new files are also checked in as loose files, and the two append-only
edits are in `main/*.append` for `main/CMakeLists.txt` and
`main/Kconfig.projbuild` (`kern-stateless.patch` is authoritative).

```sh
git clone --recursive https://github.com/odudex/Kern.git
git -C Kern checkout 7cdd258
git -C Kern apply /path/to/Phase_22/kern_changes/kern-stateless.patch
```

The clean end-to-end script applies the patch to a throwaway copy in the
gitignored `Phase_22/build/kern-work` - see
`Phase_22/tools/build_kern_stateless_emu.sh` (`RUN_EMU=0` to stop after
build/sign/merge).

## Files

| File | Purpose |
|---|---|
| `components/stateless_shim/stateless_shim.c` | IDF v6.1 replacement for `call_start_cpu0()`: `my_entry_point` trampoline, `__wrap_call_start_cpu0`, CLIC vector-table install, `_esp_sys_init_fn_start/end` + `__libc_init_array()` staging, PSRAM heap hand-off. Wraps the hardware init the loader already performed. |
| `components/stateless_shim/CMakeLists.txt` | Entry/wrap linker options (`-Wl,-e,my_entry_point`, `--wrap=call_start_cpu0`, `cache_hal_init`, `esp_psram_chip_init`, …). |
| `main/stateless_ota.c` | `--wrap=esp_ota_get_running_partition` under `CONFIG_KERN_STATELESS`. A PSRAM-XIP payload has no flash app partition, so IDF's cache2phys lookup aborts when NVS/partition-safety code calls it; this returns the payload-local metadata partition instead. Dev-only. |
| `main/CMakeLists.append` | Append to `main/CMakeLists.txt`: adds the `--wrap=esp_ota_get_running_partition` link option when `CONFIG_KERN_STATELESS=y`. |
| `main/Kconfig.projbuild.append` | Insert before the final `endmenu` in `main/Kconfig.projbuild`: the `KERN_STATELESS` option. |
| `partitions_stateless.csv` | Payload-local table at `0x10000` in the loader's free sector: `nvs @ 0x11000`, `otadata @ 0x1e000`, metadata-only `factory @ 0x30000`. The loader keeps its own table at `0x20000`; the payload's table is never used to boot anything. |
| `sdkconfig.defaults.stateless` | Unicore, single-core system, virtual eFuses, and secure-boot app checks off (the loader's Layer 2 bundle verification is authoritative). |

## Build

```sh
idf.py -B build_kern_stateless -D IDF_TARGET=esp32p4 \
  -D SDKCONFIG=build_kern_stateless/sdkconfig \
  -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.defaults.wave_43;sdkconfig.defaults.stateless" \
  build
```

Result: `build_kern_stateless/kern.bin` - 6 segments, entry `0x4FF01F90`, and a
36-byte RTC segment at `0x50108080` that the Phase 22 loader compatibility patch
must skip (see `Phase_22/loader_changes/kern-image-compat.patch`).

## Caveats

- **NVS persistence is accepted.** `nvs_secure_init()` runs against the
  payload-local `nvs` partition at `0x11000` (and `otadata` at `0x1e000`). This
  is application state (settings/PIN), not executable code; the stateless
  guarantee covers the signed payload not being installed in flash. The narrow
  `esp_ota_get_running_partition()` wrapper is still required because IDF's
  NVS write-safety check cannot map a PSRAM-XIP app.
- **No panel.** The run stops at `MIPI DSI PHY Powered on`; LCD/camera/QR and
  mainnet are out of scope for this phase.
- The payload is signed as `kern_esp32p4` with the loader's `test` profile key;
  per-platform key slots are still open.
