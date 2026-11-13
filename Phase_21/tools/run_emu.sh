#!/usr/bin/env bash
# ==============================================================================
# Phase 21 emulator rig - stateless-bootloader end-to-end on esp-emu (>=0.49).
#
# QEMU cannot do this: the Espressif QEMU fork has no ESP32-P4 machine at all
# (not even in the IDF v6.1 bundle), and its ESP32-S3 machine models no SD
# card. esp-emu models P4/S3 ROM + PSRAM but no SD card either, so payloads
# ride in raw flash (EMU_FLASH_PAYLOAD) while everything downstream of
# storage stays the unmodified production path.
#
# Actions:
#   s3-halt   faithful S3 loader (secure boot ON) -> fail-closed "No SD" halt
#   p4-halt   faithful P4 loader (rev 3.1, secure boot ON) -> same halt
#   s3-e2e    S3 loader + flash-injected signed bundle -> payload boot
#               (needs PAYLOAD_BIN: raw ESP image, e.g. Phase_15 hello shim or
#               seedsigner-micropython-builder S3 micropython.bin)
#   p4-e2e    P4 rev-3.1 route: loader (rev-3.1 fragment) + flash-injected signed
#               bundle -> payload boot (needs PAYLOAD_BIN: rev-3.1-matched raw image)
#   p4-rev13-e2e  P4 rev-1.3 route (matches the physical boards): production-defaults
#               loader (must carry the E8 image-header staging - upstream since
#               0361736; the rig fails fast if BOOTLOADER_DIR predates it) + rev0 ROM
#               + rev1.3 virtual eFuse; needs PAYLOAD_BIN: any pre-v3 raw ESP image
#               (e.g. Phase_11 hello or a stock pre-v3 micropython.bin) - see doc §4.6
#
# Prereqs: ESP-IDF 5.5 exported (or set IDF_PATH), esp-emu on PATH,
#   python3 ecdsa + bech32 for signing.
# Env: BOOTLOADER_DIR (default ~/Desktop/seedsigner-esp32-bootloader),
#   SCRATCH (default /tmp/emu_phase21), PAYLOAD_BIN (for the e2e actions),
#   P4_REV0_ROM (for p4-rev13-e2e; default: first esp-rom-elfs/*/esp32p4_rev0_rom.elf).
# ==============================================================================
set -uo pipefail

PHASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BOOTLOADER_DIR="${BOOTLOADER_DIR:-$HOME/Desktop/seedsigner-esp32-bootloader}"
SCRATCH="${SCRATCH:-/tmp/emu_phase21}"
ACTION="${1:-s3-e2e}"

if ! command -v idf.py >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    . "$HOME/esp/esp-idf-v5.5/export.sh" >/dev/null 2>&1 || true
fi
command -v idf.py >/dev/null 2>&1 || { echo "idf.py not found"; exit 1; }
command -v esp-emu >/dev/null 2>&1 || { echo "esp-emu not found"; exit 1; }

EMU_BUNDLE_OFF=0x13FF00   # Specter header; ESP image lands at 0x140000 (64K-aligned)

prep_scratch() {  # $1 = 1 to apply the EMU_FLASH_PAYLOAD patch
    rm -rf "$SCRATCH"; mkdir -p "$SCRATCH"
    for f in main components keys tools CMakeLists.txt partitions_esp32s3.csv \
             partitions_esp32p4.csv sdkconfig.defaults sdkconfig.defaults.esp32s3 \
             sdkconfig.defaults.esp32p4 secure_boot_signing_key.pem \
             payload_signing_key.pem; do
        if [ -e "$BOOTLOADER_DIR/$f" ]; then
            cp -r "$BOOTLOADER_DIR/$f" "$SCRATCH/"
        else
            echo "prep_scratch: absent in $BOOTLOADER_DIR, skipping: $f"
        fi
    done
    if [ "$1" = "1" ]; then
        patch -d "$SCRATCH" -p1 < "$PHASE_DIR/loader_changes/emu-flash-payload.patch"
    fi
}

require_header_staging() {  # E8: the 32-byte image-header staging must be in the loader source
    # The staging was dropped in 354e0bf and restored upstream in 0361736 (both the P4
    # and S3 mapped-segment branches). Without it, call_start_cpu0-path payloads abort
    # with "Invalid app image header" right after JMP (doc E8).
    if ! grep -q "last_page_start" "$SCRATCH/main/esp_image.c"; then
        echo "p4-rev13-e2e: loader source predates the E8 header-staging fix (upstream 0361736):"
        echo "  $SCRATCH/main/esp_image.c has no 'last_page_start' staging."
        echo "  Update $BOOTLOADER_DIR to 0361736 or newer (call_start_cpu0-path payloads"
        echo "  would abort in the mapped fake_flash window)."
        exit 1
    fi
}

build_loader() {  # $1 target, $2 build dir, $3 extra defaults ("" or fragment), $4 emu flag (0/1)
    local B="$SCRATCH/$2"
    rm -rf "$B"
    local DEFAULTS="$SCRATCH/sdkconfig.defaults;$SCRATCH/sdkconfig.defaults.$1"
    [ -n "$3" ] && DEFAULTS="$DEFAULTS;$3"
    if [ "$4" = "1" ]; then export EMU_FLASH_PAYLOAD=1; else unset EMU_FLASH_PAYLOAD; fi
    idf.py -C "$SCRATCH" -B "$B" -D IDF_TARGET="$1" -D SDKCONFIG="$B/sdkconfig" \
        -D SDKCONFIG_DEFAULTS="$DEFAULTS" reconfigure
    idf.py -C "$SCRATCH" -B "$B" build
}

merge_s3() {  # $1 build dir, $2 out, [$3 bundle]
    . "$HOME/esp/esp-idf-v5.5/export.sh" >/dev/null 2>&1 || true
    if [ -n "${3:-}" ]; then
        python3 -m esptool --chip esp32s3 merge_bin -o "$2" \
            --flash_mode keep --flash_freq keep --flash_size keep \
            0x0 "$SCRATCH/$1/bootloader/bootloader.bin" \
            0x10000 "$SCRATCH/$1/partition_table/partition-table.bin" \
            0x20000 "$SCRATCH/$1/seedsigner_secure_loader.bin" \
            "$EMU_BUNDLE_OFF" "$3"
    else
        python3 -m esptool --chip esp32s3 merge_bin -o "$2" \
            --flash_mode keep --flash_freq keep --flash_size keep \
            0x0 "$SCRATCH/$1/bootloader/bootloader.bin" \
            0x10000 "$SCRATCH/$1/partition_table/partition-table.bin" \
            0x20000 "$SCRATCH/$1/seedsigner_secure_loader.bin"
    fi
}

merge_p4() {  # $1 build dir, $2 out, [$3 bundle]
    . "$HOME/esp/esp-idf-v5.5/export.sh" >/dev/null 2>&1 || true
    if [ -n "${3:-}" ]; then
        python3 -m esptool --chip esp32p4 merge_bin -o "$2" \
            --flash_mode keep --flash_freq keep --flash_size keep \
            0x2000 "$SCRATCH/$1/bootloader/bootloader.bin" \
            0x20000 "$SCRATCH/$1/partition_table/partition-table.bin" \
            0x30000 "$SCRATCH/$1/seedsigner_secure_loader.bin" \
            "$EMU_BUNDLE_OFF" "$3"
    else
        python3 -m esptool --chip esp32p4 merge_bin -o "$2" \
            --flash_mode keep --flash_freq keep --flash_size keep \
            0x2000 "$SCRATCH/$1/bootloader/bootloader.bin" \
            0x20000 "$SCRATCH/$1/partition_table/partition-table.bin" \
            0x30000 "$SCRATCH/$1/seedsigner_secure_loader.bin"
    fi
}

case "$ACTION" in
    s3-halt)
        prep_scratch 0
        build_loader esp32s3 build-s3 "" 0
        merge_s3 build-s3 "$SCRATCH/s3halt.bin"
        esp-emu --chip esp32s3 --firmware "$SCRATCH/s3halt.bin" --psram-size 8M --timeout 90s
        ;;
    p4-halt)
        prep_scratch 0
        build_loader esp32p4 build-p4 "$PHASE_DIR/tools/emu_rev_p4.defaults" 0
        merge_p4 build-p4 "$SCRATCH/phalt.bin"
        esp-emu --chip esp32p4 --firmware "$SCRATCH/phalt.bin" --psram-size 32M --timeout 30s
        ;;
    s3-e2e)
        [ -n "${PAYLOAD_BIN:-}" ] || { echo "Set PAYLOAD_BIN=<raw .bin ESP image>"; exit 1; }
        [ -f "$PAYLOAD_BIN" ] || { echo "Missing: $PAYLOAD_BIN"; exit 1; }
        prep_scratch 1
        build_loader esp32s3 build-s3-emu "" 1
        BUNDLE="$SCRATCH/bundle.bin"
        python3 "$SCRATCH/tools/generate_signed_payload.py" --platform seedsigner_esp32s3 \
            --profile test --key "$SCRATCH/payload_signing_key.pem" "$PAYLOAD_BIN" "$BUNDLE"
        merge_s3 build-s3-emu "$SCRATCH/s3e2e.bin" "$BUNDLE"
        echo "Merged: $SCRATCH/s3e2e.bin -- boot it, e.g.:"
        echo "  esp-emu --chip esp32s3 --firmware $SCRATCH/s3e2e.bin --psram-size 8M --timeout 840s"
        ;;
    p4-e2e)
        [ -n "${PAYLOAD_BIN:-}" ] || { echo "Set PAYLOAD_BIN=<raw .bin ESP image>"; exit 1; }
        [ -f "$PAYLOAD_BIN" ] || { echo "Missing: $PAYLOAD_BIN"; exit 1; }
        prep_scratch 1
        build_loader esp32p4 build-p4-emu "$PHASE_DIR/tools/emu_rev_p4.defaults" 1
        BUNDLE="$SCRATCH/bundle.bin"
        python3 "$SCRATCH/tools/generate_signed_payload.py" --platform seedsigner_esp32p4 \
            --profile test --key "$SCRATCH/payload_signing_key.pem" "$PAYLOAD_BIN" "$BUNDLE"
        merge_p4 build-p4-emu "$SCRATCH/p4e2e.bin" "$BUNDLE"
        echo "Merged: $SCRATCH/p4e2e.bin -- boot it, e.g.:"
        echo "  esp-emu --chip esp32p4 --firmware $SCRATCH/p4e2e.bin --psram-size 32M --timeout 840s"
        ;;
    p4-rev13-e2e)
        [ -n "${PAYLOAD_BIN:-}" ] || { echo "Set PAYLOAD_BIN=<raw .bin ESP image>"; exit 1; }
        [ -f "$PAYLOAD_BIN" ] || { echo "Missing: $PAYLOAD_BIN"; exit 1; }
        P4_REV0_ROM="${P4_REV0_ROM:-$(ls -1 "$HOME"/.espressif/tools/esp-rom-elfs/*/esp32p4_rev0_rom.elf 2>/dev/null | head -1)}"
        [ -n "$P4_REV0_ROM" ] || { echo "Set P4_REV0_ROM=<esp32p4_rev0_rom.elf> (install the esp-rom-elfs package via idf_tools.py)"; exit 1; }
        prep_scratch 1
        require_header_staging
        build_loader esp32p4 build-p4-rev13-emu "" 1
        BUNDLE="$SCRATCH/bundle.bin"
        python3 "$SCRATCH/tools/generate_signed_payload.py" --platform seedsigner_esp32p4 \
            --profile test --key "$SCRATCH/payload_signing_key.pem" "$PAYLOAD_BIN" "$BUNDLE"
        merge_p4 build-p4-rev13-emu "$SCRATCH/p4rev13e2e.bin" "$BUNDLE"
        python3 "$PHASE_DIR/tools/make-efuse.py" --chip esp32p4 --chip-rev 1.3 -o "$SCRATCH/efuse_p4_rev1.3.bin"
        echo "Merged: $SCRATCH/p4rev13e2e.bin -- boot it (rev-1.3 route), e.g.:"
        echo "  esp-emu --chip esp32p4 --firmware $SCRATCH/p4rev13e2e.bin --psram-size 32M \\"
        echo "    --rom $P4_REV0_ROM --efuse $SCRATCH/efuse_p4_rev1.3.bin --timeout 240s"
        ;;
    *) echo "Usage: $0 [s3-halt|p4-halt|s3-e2e|p4-e2e|p4-rev13-e2e]"; exit 1 ;;
esac
