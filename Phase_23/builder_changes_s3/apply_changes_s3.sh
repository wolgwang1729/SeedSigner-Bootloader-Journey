#!/usr/bin/env bash
# ==============================================================================
# apply_changes_s3.sh - Applies Phase 23 headless PSBT signing overlay & patches
# to seedsigner-micropython-builder for ESP32-S3.
#
# Usage:
#   ./apply_changes_s3.sh [--revert] [path/to/seedsigner-micropython-builder]
#
# Default target: ~/Desktop/seedsigner-micropython-builder
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOB_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REVERT=0

if [ "${1:-}" = "--revert" ]; then
    REVERT=1
    shift
fi

TARGET_DIR="${1:-$HOME/Desktop/seedsigner-micropython-builder}"

echo "=== SeedSigner MicroPython Builder - Phase 23 S3 Overlay Applicator ==="
echo "Source: $SCRIPT_DIR"
echo "Target: $TARGET_DIR"
echo "Action: $([ $REVERT -eq 1 ] && echo 'REVERT' || echo 'APPLY')"

if [ ! -d "$TARGET_DIR" ]; then
    echo "ERROR: Target directory does not exist: $TARGET_DIR" >&2
    exit 1
fi

BOARD_NAME="WAVESHARE_ESP32_S3_TOUCH_LCD_35B"
BOARD_MOD_DIR="$TARGET_DIR/deps/micropython/mods/new_files/ports/esp32/boards/$BOARD_NAME"
MODULES_MOD_DIR="$TARGET_DIR/deps/micropython/mods/new_files/ports/esp32/modules"

if [ $REVERT -eq 1 ]; then
    echo "--> 1. Reverting patches..."
    if (cd "$TARGET_DIR" && git apply -R --check "$SCRIPT_DIR/patches/0002-s3-stateless-shim-extmem.patch" 2>/dev/null); then
        (cd "$TARGET_DIR" && git apply -R "$SCRIPT_DIR/patches/0002-s3-stateless-shim-extmem.patch")
        echo "    Reverted 0002-s3-stateless-shim-extmem.patch"
    else
        echo "    Patch 0002 not applied or already clean."
    fi

    if (cd "$TARGET_DIR" && git apply -R --check "$SCRIPT_DIR/patches/0001-s3-mpconfigboard-manifest.patch" 2>/dev/null); then
        (cd "$TARGET_DIR" && git apply -R "$SCRIPT_DIR/patches/0001-s3-mpconfigboard-manifest.patch")
        echo "    Reverted 0001-s3-mpconfigboard-manifest.patch"
    else
        echo "    Patch 0001 not applied or already clean."
    fi

    echo "--> 2. Removing manifest.py from board dir..."
    rm -f "$BOARD_MOD_DIR/manifest.py"

    echo "--> 3. Removing _boot.py from modules dir..."
    rm -f "$MODULES_MOD_DIR/_boot.py"

    echo "--> 4. Removing staged headless fixture and runner files from frozen_app/..."
    rm -f "$TARGET_DIR/frozen_app/_headless_fixtures.py" "$TARGET_DIR/frozen_app/_headless_signer.py"

    echo "=== Phase 23 S3 changes reverted cleanly ==="
    exit 0
fi

echo "--> 1. Staging headless fixture and runner into frozen_app/..."
mkdir -p "$TARGET_DIR/frozen_app"
cp -v "$SOB_ROOT/Phase_23/fixtures/_headless_fixtures.py" "$TARGET_DIR/frozen_app/"
cp -v "$SOB_ROOT/Phase_23/fixtures/_headless_signer.py" "$TARGET_DIR/frozen_app/"

echo "--> 2. Applying patches..."
if (cd "$TARGET_DIR" && git apply --check "$SCRIPT_DIR/patches/0001-s3-mpconfigboard-manifest.patch" 2>/dev/null); then
    (cd "$TARGET_DIR" && git apply "$SCRIPT_DIR/patches/0001-s3-mpconfigboard-manifest.patch")
    echo "    Applied 0001-s3-mpconfigboard-manifest.patch"
else
    echo "    Patch 0001 already applied or conflict."
fi

if (cd "$TARGET_DIR" && git apply --check "$SCRIPT_DIR/patches/0002-s3-stateless-shim-extmem.patch" 2>/dev/null); then
    (cd "$TARGET_DIR" && git apply "$SCRIPT_DIR/patches/0002-s3-stateless-shim-extmem.patch")
    echo "    Applied 0002-s3-stateless-shim-extmem.patch"
else
    echo "    Patch 0002 already applied or conflict."
fi

echo "--> 3. Staging manifest.py into board dir..."
mkdir -p "$BOARD_MOD_DIR"
cp -v "$SCRIPT_DIR/files/manifest.py" "$BOARD_MOD_DIR/manifest.py"

echo "--> 4. Staging _boot.py into modules dir..."
mkdir -p "$MODULES_MOD_DIR"
cp -v "$SCRIPT_DIR/files/_boot.py" "$MODULES_MOD_DIR/_boot.py"

echo "=== Phase 23 S3 changes applied successfully ==="
