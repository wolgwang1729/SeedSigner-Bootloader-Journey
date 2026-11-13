#!/usr/bin/env bash
# ==============================================================================
# Phase 22 - Kern baseline on esp-emu (P4 rev 1.3, virtual eFuses, IDF v6.1).
#
# Clones Kern if missing, builds the wave_43 (pre-v3) image with a virtual-eFuse
# overlay, merges bootloader + partition table + OTA data + app, generates a
# rev-1.3 eFuse blob for esp-emu, and boots it with the pre-v3 ROM.
#
# This is a *baseline* run: no stateless loader, no SD card, no signature
# changes. It proves the unmodified Kern image boots through the real ROM +
# 2nd-stage bootloader in emu until the first absent-hardware blocker.
#
# Env:
#   KERN_DIR       default Phase_22/build/Kern (cloned if missing)
#   IDF_PATH_6_1   default ~/esp/esp-idf-v6.1
#   BOARD          default wave_43
#   BUILD_DIR      default build_${BOARD}_emu
#   PSRAM_SIZE     default 32M
#   TIMEOUT        default 180s
#   P4_REV0_ROM    default newest esp-rom-elfs/*/esp32p4_rev0_rom.elf
#   RUN_EMU=0      build/merge only, do not launch esp-emu
# ==============================================================================
set -euo pipefail

PHASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KERN_DIR="${KERN_DIR:-$PHASE_DIR/build/Kern}"
IDF_PATH_6_1="${IDF_PATH_6_1:-$HOME/esp/esp-idf-v6.1}"
BOARD="${BOARD:-wave_43}"
BUILD_DIR="${BUILD_DIR:-build_${BOARD}_emu}"
PSRAM_SIZE="${PSRAM_SIZE:-32M}"
TIMEOUT="${TIMEOUT:-180s}"
RUN_EMU="${RUN_EMU:-1}"

command -v esp-emu >/dev/null 2>&1 || { echo "esp-emu not found on PATH"; exit 1; }
[ -d "$IDF_PATH_6_1" ] || { echo "ESP-IDF 6.1 not found: $IDF_PATH_6_1"; exit 1; }

if [ ! -d "$KERN_DIR/.git" ]; then
    echo "Cloning Kern into $KERN_DIR ..."
    git clone --recursive --shallow-submodules --depth 1 \
        https://github.com/odudex/Kern.git "$KERN_DIR"
fi

# Virtual eFuses: no physical burns, and the HMAC/NVS/secure-boot code paths
# see a RAM-backed eFuse store. KEEP_IN_FLASH is deliberately not set (Kern has
# no `efuse` partition; a single emu boot does not need persistence).
cat > "$KERN_DIR/sdkconfig.defaults.emu" <<'EOF'
CONFIG_EFUSE_VIRTUAL=y
CONFIG_EFUSE_VIRTUAL_LOG_ALL_WRITES=y
EOF

# shellcheck disable=SC1090
. "$IDF_PATH_6_1/export.sh" >/dev/null 2>&1
idf.py --version | grep -q "v6.1" || {
    echo "Expected ESP-IDF v6.1, got: $(idf.py --version)"; exit 1;
}

cd "$KERN_DIR"
idf.py -B "$BUILD_DIR" -D IDF_TARGET=esp32p4 \
    -D SDKCONFIG="$BUILD_DIR/sdkconfig" \
    -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.defaults.${BOARD};sdkconfig.defaults.emu" \
    build

python -m esptool --chip esp32p4 merge-bin \
    -o "$BUILD_DIR/kern_emu.bin" \
    --flash-mode dio --flash-freq 80m --flash-size 16MB \
    0x2000 "$BUILD_DIR/bootloader/bootloader.bin" \
    0x10000 "$BUILD_DIR/partition_table/partition-table.bin" \
    0x1e000 "$BUILD_DIR/ota_data_initial.bin" \
    0x20000 "$BUILD_DIR/kern.bin"

EFUSE_BIN="${EFUSE_BIN:-$PHASE_DIR/build/kern_efuse_p4_rev1.3.bin}"
python3 "$PHASE_DIR/../Phase_21/tools/make-efuse.py" \
    --chip esp32p4 --chip-rev 1.3 -o "$EFUSE_BIN"

P4_REV0_ROM="${P4_REV0_ROM:-$(ls -1 "$HOME"/.espressif/tools/esp-rom-elfs/*/esp32p4_rev0_rom.elf 2>/dev/null | tail -1)}"
[ -n "$P4_REV0_ROM" ] || { echo "Set P4_REV0_ROM=<esp32p4_rev0_rom.elf>"; exit 1; }

echo "Merged: $KERN_DIR/$BUILD_DIR/kern_emu.bin"
echo "eFuse:  $EFUSE_BIN (virtual, emulator-only)"
if [ "$RUN_EMU" = "1" ]; then
    mkdir -p "$PHASE_DIR/logs"
    esp-emu --chip esp32p4 --firmware "$KERN_DIR/$BUILD_DIR/kern_emu.bin" \
        --psram-size "$PSRAM_SIZE" --rom "$P4_REV0_ROM" --efuse "$EFUSE_BIN" \
        --timeout "$TIMEOUT" 2>&1 | tee "$PHASE_DIR/logs/kern_emu_first_boot.txt"
fi
