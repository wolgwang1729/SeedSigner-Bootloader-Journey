#!/usr/bin/env bash
# apply_changes.sh — Applies Phase 18 changes to seedsigner-micropython-builder
#
# Usage:
#   ./apply_changes.sh [path/to/seedsigner-micropython-builder]
#
# Default target: ~/Desktop/seedsigner-micropython-builder-upstream

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-$HOME/Desktop/seedsigner-micropython-builder-upstream}"

echo "=== SeedSigner MicroPython Builder — Phase 18 Overlay Applicator ==="
echo "Source: $SCRIPT_DIR"
echo "Target: $TARGET_DIR"

if [ ! -d "$TARGET_DIR" ]; then
    echo "ERROR: Target directory does not exist: $TARGET_DIR"
    exit 1
fi

if [ ! -f "$TARGET_DIR/Makefile" ] || [ ! -d "$TARGET_DIR/deps/micropython" ]; then
    echo "ERROR: $TARGET_DIR does not look like a seedsigner-micropython-builder repository."
    exit 1
fi

echo "--> 1. Copying builder files and overlay from files/ to $TARGET_DIR..."
cp -rv "$SCRIPT_DIR/files/"* "$TARGET_DIR/"

echo "--> 2. Ensuring board files are mirrored into micropython upstream tree..."
# When building with MP_ALLOW_DIRTY=1, MicroPython does not automatically re-apply the overlay,
# so the new board files must be synced directly into deps/micropython/upstream:
BOARD_MODS_DIR="$TARGET_DIR/deps/micropython/mods/new_files/ports/esp32/boards/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43"
BOARD_UPSTREAM_DIR="$TARGET_DIR/deps/micropython/upstream/ports/esp32/boards/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43"

if [ -d "$TARGET_DIR/deps/micropython/upstream/ports/esp32" ]; then
    mkdir -p "$BOARD_UPSTREAM_DIR"
    rsync -av "$BOARD_MODS_DIR/" "$BOARD_UPSTREAM_DIR/"
    cp -v "$TARGET_DIR/deps/micropython/mods/new_files/ports/esp32/partitions-stateless.csv" \
          "$TARGET_DIR/deps/micropython/upstream/ports/esp32/"
fi

# Also mirror board_common if _local_ws was used for local builds
if [ -d "$TARGET_DIR/_local_ws/esp-board-common" ]; then
    echo "--> Updating _local_ws/esp-board-common mirror..."
    rsync -av "$TARGET_DIR/ports/esp32/board_common/" "$TARGET_DIR/_local_ws/esp-board-common/"
fi

echo "--> 3. Checking git status of modified submodules..."
if [ -d "$TARGET_DIR/.git" ]; then
    (cd "$TARGET_DIR" && git status -s)
fi

echo "=== Phase 18 changes applied successfully! ==="
echo ""
echo "To build the Slice 2 signed stateless firmware:"
echo "  cd $TARGET_DIR"
echo "  make docker-build-all \\"
echo "    BOARD=WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43 \\"
echo "    BOARD_VARIANT=PRE_REV3_STATELESS \\"
echo "    HEADLESS_VIRTUAL_FB=1 \\"
echo "    MP_ALLOW_DIRTY=1 \\"
echo "    SS_EMBIT_DIR=\$PWD/deps/embit \\"
echo "    SS_APP_DIR=\$PWD/deps/seedsigner"
echo ""
