#!/usr/bin/env bash
# ==============================================================================
# Phase 22 - Specter-DIY stateless hand-off on esp-emu (P4 rev 1.3).
#
# End-to-end reproduction:
#   1. clean sandman21vs/specter-diy @ f54e345 + Phase 22 overlay (stateless
#      shim component, stateless sdkconfig fragment, stateless build-time
#      partition table)
#   2. MicroPython master @ 8cf130db34 + Phase 22 stateless patch (_boot.py VFS
#      mount skipped, Partition NULL guard, REPL RX ISR exported)
#   3. build MicroPython for WAVESHARE_P4_43 with -DMICROPY_STATELESS=1
#   4. clean loader 976ee3a + Phase 21 flash-injection overlay + Phase 22
#      compatibility patch (accepted `specter_esp32p4` platform) -> loader with
#      SB V2 + Specter multisig
#   5. sign with the `specter_esp32p4` platform string, merge the loader and
#      payload, and boot the rev-1.3 route (rev0 ROM + virtual eFuse blob).
#
# The payload is NOT flashed into an app partition. It is injected only into
# the emulator's raw flash as a signed bundle, exactly like the Phase 21 rig.
# No physical eFuse is written.
#
# The Phase 22 workspace (source clones + work trees + bundles) is the
# gitignored Phase_22/build/; the defaults below use it, and it is safe to
# delete at any time (a rebuild recreates it).
#
# Env:
#   SPECTER_SRC     default Phase_22/build/specter-p4
#   MICROPYTHON_DIR default Phase_22/build/micropython
#   LOADER_SRC      default ~/Desktop/seedsigner-esp32-bootloader
#   WORK            default Phase_22/build/specter-work
#   IDF_5_5         default ~/esp/esp-idf-v5.5
#   SPECTER_COMMIT  default f54e345
#   MICROPYTHON_REF default 8cf130db34
#   LOADER_COMMIT   default 976ee3a
#   TIMEOUT         default 300s (the app stops at display init; no need to wait
#                   for the full timeout once the stall is reproduced)
#   PSRAM_SIZE      default 32M
#   RUN_EMU=0       build/sign/merge only
#   EMU_GDB=1       add --gdb 1234 --elf <payload elf>; attach with
#                   riscv32-esp-elf-gdb -ex 'target remote :1234' -ex bt \\
#                     "$WORK/build-W43/micropython.elf"
# ==============================================================================
set -euo pipefail

PHASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPECTER_SRC="${SPECTER_SRC:-$PHASE_DIR/build/specter-p4}"
MICROPYTHON_DIR="${MICROPYTHON_DIR:-$PHASE_DIR/build/micropython}"
LOADER_SRC="${LOADER_SRC:-$HOME/Desktop/seedsigner-esp32-bootloader}"
WORK="${WORK:-$PHASE_DIR/build/specter-work}"
IDF_5_5="${IDF_5_5:-$HOME/esp/esp-idf-v5.5}"
SPECTER_COMMIT="${SPECTER_COMMIT:-f54e345}"
MICROPYTHON_REF="${MICROPYTHON_REF:-8cf130db34}"
LOADER_COMMIT="${LOADER_COMMIT:-976ee3a}"
TIMEOUT="${TIMEOUT:-300s}"
PSRAM_SIZE="${PSRAM_SIZE:-32M}"

for f in \
    "$PHASE_DIR/specter_changes/specter-stateless.patch" \
    "$PHASE_DIR/specter_changes/micropython-stateless.patch" \
    "$PHASE_DIR/specter_changes/stateless_shim/stateless_shim.c" \
    "$PHASE_DIR/specter_changes/stateless_shim/CMakeLists.txt" \
    "$PHASE_DIR/specter_changes/stateless_shim/Kconfig" \
    "$PHASE_DIR/specter_changes/sdkconfig.stateless" \
    "$PHASE_DIR/specter_changes/partitions-stateless.csv" \
    "$PHASE_DIR/loader_changes/kern-image-compat.patch" \
    "$PHASE_DIR/../Phase_21/loader_changes/emu-flash-payload.patch"; do
    [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
done
[ -d "$SPECTER_SRC/.git" ] || { echo "SPECTER_SRC is not a git checkout: $SPECTER_SRC (clone https://github.com/sandman21vs/specter-diy.git there)" >&2; exit 1; }
[ -d "$MICROPYTHON_DIR/.git" ] || { echo "MICROPYTHON_DIR is not a git checkout: $MICROPYTHON_DIR (clone https://github.com/micropython/micropython.git there)" >&2; exit 1; }
[ -d "$LOADER_SRC/.git" ] || { echo "LOADER_SRC is not a git checkout: $LOADER_SRC" >&2; exit 1; }
[ -f "$IDF_5_5/export.sh" ] || { echo "IDF_5_5 not found: $IDF_5_5" >&2; exit 1; }
command -v patch >/dev/null || { echo "patch not found" >&2; exit 1; }
command -v esp-emu >/dev/null || echo "warning: esp-emu not on PATH; RUN_EMU=0 still works"

echo "== Phase 22 clean work tree: $WORK"
rm -rf "$WORK"
mkdir -p "$WORK/specter" "$WORK/loader"

echo "== Specter $SPECTER_COMMIT -> $WORK/specter"
git -C "$SPECTER_SRC" archive "$SPECTER_COMMIT" | tar -x -C "$WORK/specter"
# Submodules are empty in `git archive`; reuse the populated checkout. Skip
# the uninitialised `bootloader` gitlink (not used by the payload build).
while IFS= read -r sub; do
    [ -n "$sub" ] || continue
    [ -d "$SPECTER_SRC/$sub" ] || continue
    [ -n "$(ls -A "$SPECTER_SRC/$sub" 2>/dev/null)" ] || continue
    mkdir -p "$WORK/specter/$(dirname "$sub")"
    rm -rf "$WORK/specter/$sub"
    cp -a "$SPECTER_SRC/$sub" "$WORK/specter/$sub"
done < <(git -C "$SPECTER_SRC" config --file .gitmodules --get-regexp '^submodule\..*\.path$' | awk '{print $2}')

# Phase 22 overlay: new files + the board's opt-in cmake wiring.
cp -a "$PHASE_DIR/specter_changes/stateless_shim" "$WORK/specter/ports/esp32p4/idf_components/"
cp "$PHASE_DIR/specter_changes/sdkconfig.stateless" \
   "$PHASE_DIR/specter_changes/partitions-stateless.csv" \
   "$WORK/specter/ports/esp32p4/boards/WAVESHARE_P4_43/"
patch -d "$WORK/specter" -p1 --forward < "$PHASE_DIR/specter_changes/specter-stateless.patch"

echo "== MicroPython $MICROPYTHON_REF stateless patch"
[ -f "$MICROPYTHON_DIR/mpy-cross/build/mpy-cross" ] || make -C "$MICROPYTHON_DIR/mpy-cross" -j"$(nproc)"
[ -d "$MICROPYTHON_DIR/lib/micropython-lib" ] || \
    git -C "$MICROPYTHON_DIR" submodule update --init --filter=blob:none lib/micropython-lib
[ -d "$MICROPYTHON_DIR/lib/berkeley-db-1.xx" ] || \
    git -C "$MICROPYTHON_DIR" submodule update --init --filter=blob:none lib/berkeley-db-1.xx
if git -C "$MICROPYTHON_DIR" apply --reverse --check "$PHASE_DIR/specter_changes/micropython-stateless.patch" >/dev/null 2>&1; then
    echo "   (already applied)"
else
    git -C "$MICROPYTHON_DIR" apply "$PHASE_DIR/specter_changes/micropython-stateless.patch"
fi

echo "== Specter payload build (ESP-IDF 5.5, -DMICROPY_STATELESS=1)"
(
    . "$IDF_5_5/export.sh" >/dev/null 2>&1
    cd "$MICROPYTHON_DIR/ports/esp32"
    idf.py -B "$WORK/build-W43" \
        -D MICROPY_BOARD=WAVESHARE_P4_43 \
        -D MICROPY_BOARD_DIR="$WORK/specter/ports/esp32p4/boards/WAVESHARE_P4_43" \
        -D MICROPY_STATELESS=1 \
        -D USER_C_MODULES="$WORK/specter/ports/esp32p4/components/micropython.cmake" \
        -D EXTRA_COMPONENT_DIRS="$WORK/specter/ports/esp32p4/idf_components" \
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

echo "== Sign Specter with platform specter_esp32p4"
(
    . "$IDF_5_5/export.sh" >/dev/null 2>&1
    cd "$WORK/loader"
    python3 tools/generate_signed_payload.py \
        --platform specter_esp32p4 --profile test \
        --key payload_signing_key.pem \
        "$WORK/build-W43/micropython.bin" \
        "$WORK/bundle_specter.bin"
)

# The shim's PSRAM heap starts at 0x49080000 (16.5 MB into PSRAM). The loader
# stages the ingested bundle and then the app image in low PSRAM, so their
# combined size must stay below that boundary or the heap would overlap the
# executing image (Phase 18 finding: image bytes handed out as RAM).
bundle_size=$(stat -c%s "$WORK/bundle_specter.bin")
image_size=$(stat -c%s "$WORK/build-W43/micropython.bin")
heap_offset=$((0x49080000 - 0x48000000))
if (( bundle_size + image_size >= heap_offset )); then
    echo "bundle+image = $((bundle_size + image_size)) bytes >= PSRAM heap offset $heap_offset" >&2
    exit 1
fi
echo "   bundle $bundle_size B + image $image_size B < heap offset $heap_offset B"

echo "== Merge loader + payload bundle"
(
    . "$IDF_5_5/export.sh" >/dev/null 2>&1
    cd "$WORK/loader"
    python3 -m esptool --chip esp32p4 merge_bin -o "$WORK/emu_specter.bin" \
        --flash_mode keep --flash_freq keep --flash_size keep \
        0x2000  build-p4-rev13-emu/bootloader/bootloader.bin \
        0x20000 build-p4-rev13-emu/partition_table/partition-table.bin \
        0x30000 build-p4-rev13-emu/seedsigner_secure_loader.bin \
        0x13FF00 "$WORK/bundle_specter.bin"
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
  payload : $WORK/build-W43/micropython.bin
  bundle  : $WORK/bundle_specter.bin
  merged  : $WORK/emu_specter.bin
  eFuse   : $WORK/efuse_p4_rev1.3.bin

Expected loader proof : MULTISIG ... PASSED, then JMP[...] entry in PSRAM
Expected shim proof   : === __wrap_call_start_cpu0 ENTERED ===
Expected app proof    : frozen main.py running (the two pyb stub lines)
Expected stop         : esp_lcd_new_dsi_bus waits for the DSI PHY PLL
                        (no MIPI DSI panel in emu / on the headless devkit)
EOF

if [ "${RUN_EMU:-1}" = "0" ]; then
    echo "RUN_EMU=0: not launching esp-emu."
    exit 0
fi

EMU_ARGS=()
if [ "${EMU_GDB:-0}" = "1" ]; then
    EMU_ARGS+=(--gdb 1234 --elf "$WORK/build-W43/micropython.elf")
    echo "GDB stub on :1234. Attach after the app stalls:"
    echo "  riscv32-esp-elf-gdb -ex 'target remote :1234' -ex bt $WORK/build-W43/micropython.elf"
fi

echo "== Boot (rev-1.3 route)"
esp-emu --chip esp32p4 --firmware "$WORK/emu_specter.bin" --psram-size "$PSRAM_SIZE" \
    --rom "$P4_REV0_ROM" --efuse "$WORK/efuse_p4_rev1.3.bin" --timeout "$TIMEOUT" \
    "${EMU_ARGS[@]}"
