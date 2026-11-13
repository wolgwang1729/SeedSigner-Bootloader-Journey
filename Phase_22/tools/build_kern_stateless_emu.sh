#!/usr/bin/env bash
# ==============================================================================
# Phase 22 - Kern stateless hand-off on esp-emu (P4 rev 1.3, IDF v6.1 payload).
#
# End-to-end reproduction:
#   1. clean Kern 7cdd258 + Phase 22 stateless patch (shim, NVS/OTA metadata,
#      unicore/virtual-eFuse overlay) -> signed payload
#   2. clean loader 976ee3a + Phase 21 flash-injection overlay + Phase 22
#      Kern compatibility patch (IDF 6.x padding segment, RTC-overlap skip,
#      accepted-platform table) -> loader with SB V2 + Specter multisig
#   3. sign with the new `kern_esp32p4` platform string, merge the loader and
#      payload, and boot the rev-1.3 route (rev0 ROM + virtual eFuse blob).
#
# The payload is NOT flashed into an app partition. It is injected only into
# the emulator's raw flash as a signed bundle, exactly like the Phase 21 rig.
# No physical eFuse is written.
#
# The Phase 22 workspace (source clones + work trees) is the gitignored
# Phase_22/build/; the defaults below use it, and it is safe to delete at any
# time (a rebuild recreates it).
#
# Env:
#   KERN_SRC       default Phase_22/build/Kern
#   LOADER_SRC     default ~/Desktop/seedsigner-esp32-bootloader
#   WORK           default Phase_22/build/kern-work
#   IDF_6_1        default ~/esp/esp-idf-v6.1
#   IDF_5_5        default ~/esp/esp-idf-v5.5
#   KERN_COMMIT    default 7cdd258
#   LOADER_COMMIT  default 976ee3a
#   TIMEOUT        default 180s
#   PSRAM_SIZE     default 32M
#   RUN_EMU=0      build/sign/merge only
# ==============================================================================
set -euo pipefail

PHASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KERN_SRC="${KERN_SRC:-$PHASE_DIR/build/Kern}"
LOADER_SRC="${LOADER_SRC:-$HOME/Desktop/seedsigner-esp32-bootloader}"
WORK="${WORK:-$PHASE_DIR/build/kern-work}"
IDF_6_1="${IDF_6_1:-$HOME/esp/esp-idf-v6.1}"
IDF_5_5="${IDF_5_5:-$HOME/esp/esp-idf-v5.5}"
KERN_COMMIT="${KERN_COMMIT:-7cdd258}"
LOADER_COMMIT="${LOADER_COMMIT:-976ee3a}"
TIMEOUT="${TIMEOUT:-180s}"
PSRAM_SIZE="${PSRAM_SIZE:-32M}"

for f in \
    "$PHASE_DIR/kern_changes/kern-stateless.patch" \
    "$PHASE_DIR/loader_changes/kern-image-compat.patch" \
    "$PHASE_DIR/../Phase_21/loader_changes/emu-flash-payload.patch"; do
    [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
done
[ -d "$KERN_SRC/.git" ] || { echo "KERN_SRC is not a git checkout: $KERN_SRC (clone https://github.com/odudex/Kern.git there)" >&2; exit 1; }
[ -d "$LOADER_SRC/.git" ] || { echo "LOADER_SRC is not a git checkout: $LOADER_SRC" >&2; exit 1; }
[ -f "$IDF_6_1/export.sh" ] || { echo "IDF_6_1 not found: $IDF_6_1" >&2; exit 1; }
[ -f "$IDF_5_5/export.sh" ] || { echo "IDF_5_5 not found: $IDF_5_5" >&2; exit 1; }
command -v patch >/dev/null || { echo "patch not found" >&2; exit 1; }
command -v esp-emu >/dev/null || echo "warning: esp-emu not on PATH; RUN_EMU=0 still works"

echo "== Phase 22 clean work tree: $WORK"
rm -rf "$WORK"
mkdir -p "$WORK/kern" "$WORK/loader"

echo "== Kern $KERN_COMMIT -> $WORK/kern"
git -C "$KERN_SRC" archive "$KERN_COMMIT" | tar -x -C "$WORK/kern"
# managed_components is fetched, not tracked. Reuse the already-resolved copy
# from the caller's checkout so the build works offline and matches the version
# IDs in dependencies.lock.
if [ -d "$KERN_SRC/managed_components" ]; then
    cp -a "$KERN_SRC/managed_components" "$WORK/kern/"
fi
if [ -f "$KERN_SRC/dependencies.lock" ]; then
    cp "$KERN_SRC/dependencies.lock" "$WORK/kern/"
fi
# Submodules are empty in `git archive`; reuse the populated checkout.
while IFS= read -r sub; do
    [ -n "$sub" ] || continue
    mkdir -p "$WORK/kern/$(dirname "$sub")"
    rm -rf "$WORK/kern/$sub"
    cp -a "$KERN_SRC/$sub" "$WORK/kern/$sub"
done < <(git -C "$KERN_SRC" config --file .gitmodules --get-regexp '^submodule\..*\.path$' | awk '{print $2}')
patch -d "$WORK/kern" -p1 --forward < "$PHASE_DIR/kern_changes/kern-stateless.patch"

echo "== Kern stateless build (ESP-IDF 6.1)"
(
    . "$IDF_6_1/export.sh" >/dev/null 2>&1
    cd "$WORK/kern"
    idf.py -B build_kern_stateless \
        -D IDF_TARGET=esp32p4 \
        -D SDKCONFIG=build_kern_stateless/sdkconfig \
        -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.defaults.wave_43;sdkconfig.defaults.stateless" \
        build
)

echo "== Loader $LOADER_COMMIT -> $WORK/loader"
git -C "$LOADER_SRC" archive "$LOADER_COMMIT" | tar -x -C "$WORK/loader"
# Signing keys are gitignored in the loader checkout; copy them into the clean
# tree. The test keys are dev-only (the same dummy profile the Phase 21 rig uses).
for key in payload_signing_key.pem secure_boot_signing_key.pem; do
    [ -f "$LOADER_SRC/$key" ] || { echo "missing test key: $LOADER_SRC/$key" >&2; exit 1; }
    cp "$LOADER_SRC/$key" "$WORK/loader/$key"
done
patch -d "$WORK/loader" -p1 --forward < "$PHASE_DIR/../Phase_21/loader_changes/emu-flash-payload.patch"
patch -d "$WORK/loader" -p1 --forward < "$PHASE_DIR/loader_changes/kern-image-compat.patch"

echo "== Loader build (ESP-IDF 5.5, EMU_FLASH_PAYLOAD=1)"
(
    . "$IDF_5_5/export.sh" >/dev/null 2>&1
    cd "$WORK/loader"
    export EMU_FLASH_PAYLOAD=1
    idf.py -B build-p4-rev13-emu \
        -D IDF_TARGET=esp32p4 \
        -D SDKCONFIG=build-p4-rev13-emu/sdkconfig \
        -D "SDKCONFIG_DEFAULTS=$PWD/sdkconfig.defaults;$PWD/sdkconfig.defaults.esp32p4" \
        reconfigure
    idf.py -B build-p4-rev13-emu build
)

echo "== Sign Kern with platform kern_esp32p4"
(
    . "$IDF_5_5/export.sh" >/dev/null 2>&1
    cd "$WORK/loader"
    python3 tools/generate_signed_payload.py \
        --platform kern_esp32p4 --profile test \
        --key payload_signing_key.pem \
        "$WORK/kern/build_kern_stateless/kern.bin" \
        "$WORK/bundle_kern.bin"
)

echo "== Merge loader + payload bundle"
(
    . "$IDF_5_5/export.sh" >/dev/null 2>&1
    cd "$WORK/loader"
    python3 -m esptool --chip esp32p4 merge_bin -o "$WORK/emu_kern.bin" \
        --flash_mode keep --flash_freq keep --flash_size keep \
        0x2000  build-p4-rev13-emu/bootloader/bootloader.bin \
        0x10000 "$WORK/kern/build_kern_stateless/partition_table/partition-table.bin" \
        0x1e000 "$WORK/kern/build_kern_stateless/ota_data_initial.bin" \
        0x20000 build-p4-rev13-emu/partition_table/partition-table.bin \
        0x30000 build-p4-rev13-emu/seedsigner_secure_loader.bin \
        0x13FF00 "$WORK/bundle_kern.bin"
)

echo "== Virtual rev-1.3 eFuse blob + ROM"
P4_REV0_ROM="${P4_REV0_ROM:-$(ls -1 "$HOME"/.espressif/tools/esp-rom-elfs/*/esp32p4_rev0_rom.elf 2>/dev/null | head -1)}"
[ -n "${P4_REV0_ROM:-}" ] || { echo "set P4_REV0_ROM to esp32p4_rev0_rom.elf" >&2; exit 1; }
(
    cd "$WORK/loader"
    . "$IDF_5_5/export.sh" >/dev/null 2>&1
    python3 "$PHASE_DIR/../Phase_21/tools/make-efuse.py" \
        --chip esp32p4 --chip-rev 1.3 -o "$WORK/efuse_p4_rev1.3.bin"
)

cat <<EOF

Built:
  payload : $WORK/kern/build_kern_stateless/kern.bin
  bundle  : $WORK/bundle_kern.bin
  merged  : $WORK/emu_kern.bin
  eFuse   : $WORK/efuse_p4_rev1.3.bin

Expected final line: wave_43: MIPI DSI PHY Powered on
Expected app proof : main_task: Calling app_main() (after [KERN-SHIM] jumping)
EOF

if [ "${RUN_EMU:-1}" = "0" ]; then
    echo "RUN_EMU=0: not launching esp-emu."
    exit 0
fi

echo "== Boot (rev-1.3 route)"
esp-emu --chip esp32p4 --firmware "$WORK/emu_kern.bin" --psram-size "$PSRAM_SIZE" \
    --rom "$P4_REV0_ROM" --efuse "$WORK/efuse_p4_rev1.3.bin" --timeout "$TIMEOUT"
