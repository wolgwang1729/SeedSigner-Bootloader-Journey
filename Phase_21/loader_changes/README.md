# loader_changes - Phase 21 Emulation Overlays

This directory documents the lightweight flash payload overlay patch used strictly during headless emulation runs in `esp-emu`.

## `emu-flash-payload.patch`

Diff applied to a scratch copy of `seedsigner-esp32-bootloader` by [tools/run_emu.sh](../tools/run_emu.sh):

1. `main/CMakeLists.txt`: Accepts compile definition `EMU_FLASH_PAYLOAD` from environment variable.
2. `main/targets/esp32s3/storage_s3.c`: Under `#ifdef EMU_FLASH_PAYLOAD`, reads the signed Specter bundle directly from raw flash at offset `0x13FF00` via ROM function `esp_rom_spiflash_read` (placing the internal image header at `0x140000`).
3. `main/targets/esp32p4/storage_p4.c`: Implements the identical raw flash read at `0x13FF00` for ESP32-P4.

### Retired Identity-Copy Workaround

An earlier revision of this patch carried a hunk for `main/targets/esp32p4/jump_p4.c` (`JMP[6.5]`) that copied mapped segments to their flat PSRAM alias because esp-emu <= 0.49.0 ignored runtime S-MMU register writes. Upstream maintainers fixed this in esp-emu v0.50.0 ([esp-emulator#24](https://github.com/espressif/esp-emulator/issues/24)), so the workaround was removed. The patch now leaves the jump and remap code completely identical to mainline.

### Operational Rules

- **Scratch Copy Only:** Never apply this patch directly to the mainline repository. `tools/run_emu.sh` applies it dynamically in a temporary directory (`/tmp/...`).
- **Untouched Verification Pipeline:** The bundle verification routines (`specter_crypto` SHA-256 hash and secp256k1 multisig checks) remain 100% untouched. Tampered or corrupted bundles halt fail-closed.
- **Flash Layout Safety:** Bundle offset `0x13FF00` sits ahead of the payload and `random_fill` region (`0x220000` on S3, `0x230000` on P4); initial boot flash-fill operations do not overwrite it.

## Retired Image-Header Staging Patch (Landed Upstream)

During Phase 21 rev-1.3 testing, a loader regression was identified: `call_start_cpu0` payloads aborted on boot (`Invalid app image header`) because the 32-byte image-header staging was dropped during an earlier refactor. 

This fix was verified in emulation and landed in the mainline bootloader repository as commit `0361736` ("fix(loader): stage image header for MMU-mapped payload segments", October 19, 2026), verified on physical ESP32-P4 rev 1.3 silicon. The test rig now guards for this fix upstream rather than applying a local patch.
