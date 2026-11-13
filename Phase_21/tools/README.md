# Phase 21 Host and Emulation Tools

This directory contains automation scripts, configuration fragments, and terminal clients for running the stateless bootloader and payload test suite on the Espressif emulator (`esp-emu >= 0.50.0`).

## Tool Inventory

| File | Purpose |
|---|---|
| `run_emu.sh` | One-command emulation test rig supporting 5 targets: `s3-halt` (faithful ESP32-S3 Secure Boot V2 boot to fail-closed no-SD halt), `p4-halt` (faithful ESP32-P4 Secure Boot V2 boot to fail-closed no-SD halt), `s3-e2e` (S3 full boot with `EMU_FLASH_PAYLOAD` overlay), `p4-e2e` (P4 rev-3.1 route with overlay), and `p4-rev13-e2e` (P4 rev-1.3 route matching physical dev boards with rev0 ROM and rev1.3 virtual eFuse). |
| `emu_rev_p4.defaults` | Revision matching build fragment (`CONFIG_ESP32P4_REV_MIN_301=y`) for esp-emu default eco5 ROM models. Secure Boot V2 remains fully enabled. |
| `emu_nosb.defaults` | Historical debug configuration fragment with Secure Boot V2 disabled. Retained for documentation; superseded by `emu_rev_p4.defaults`. |
| `repl_client.py` | TCP terminal client for connecting to `esp-emu --uart-tcp 127.0.0.1:5555`. Sends carriage return (`\r`) line endings required by MicroPython `readline` for interactive command execution. |
| `make-efuse.py` | Generates the virtual eFuse binary blob for esp-emu `--efuse` to emulate specific silicon revisions (`--chip esp32p4 --chip-rev 1.3`). |

## Usage Notes

- All tools operate strictly in emulation and do not affect physical silicon firmware builds.
- The test rig requires **esp-emu >= 0.50.0** for ESP32-P4 end-to-end execution. Upstream maintainers resolved the dynamic Cache MMU translation gap ([espressif/esp-emulator#24](https://github.com/espressif/esp-emulator/issues/24)), allowing the temporary `JMP[6.5]` identity-copy workaround to be retired.
- `p4-rev13-e2e` uses the production-defaults bootloader and checks for the upstream image-header staging fix (`0361736`). It requires the ESP-IDF `esp-rom-elfs` package (`esp32p4_rev0_rom.elf`).
