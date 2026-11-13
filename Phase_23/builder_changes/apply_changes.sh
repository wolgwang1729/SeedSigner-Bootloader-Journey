#!/usr/bin/env bash
# ==============================================================================
# apply_changes.sh - Applies Phase 23 headless PSBT signing overlay & patches
# to seedsigner-micropython-builder.
#
# Usage:
#   ./apply_changes.sh [--revert] [path/to/seedsigner-micropython-builder]
#
# Default target: ~/Desktop/seedsigner-micropython-builder-upstream
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REVERT=0

if [ "${1:-}" = "--revert" ]; then
    REVERT=1
    shift
fi

TARGET_DIR="${1:-$HOME/Desktop/seedsigner-micropython-builder-upstream}"

echo "=== SeedSigner MicroPython Builder - Phase 23 Overlay Applicator ==="
echo "Source: $SCRIPT_DIR"
echo "Target: $TARGET_DIR"
echo "Action: $([ $REVERT -eq 1 ] && echo 'REVERT' || echo 'APPLY')"

if [ ! -d "$TARGET_DIR" ]; then
    echo "ERROR: Target directory does not exist: $TARGET_DIR" >&2
    exit 1
fi

if [ ! -f "$TARGET_DIR/Makefile" ] || [ ! -d "$TARGET_DIR/deps/micropython" ]; then
    echo "ERROR: $TARGET_DIR does not look like a seedsigner-micropython-builder repository." >&2
    exit 1
fi

BOARD_NAME="WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43"
MANIFEST_MOD="$TARGET_DIR/deps/micropython/mods/new_files/ports/esp32/boards/$BOARD_NAME/manifest.py"
MANIFEST_UPSTREAM="$TARGET_DIR/deps/micropython/upstream/ports/esp32/boards/$BOARD_NAME/manifest.py"
UPSTREAM_DIR="$TARGET_DIR/deps/micropython/upstream"

if [ $REVERT -eq 1 ]; then
    echo "--> 1. Reverting main.c patch in micropython upstream..."
    if (cd "$UPSTREAM_DIR" && git apply -R --check "$SCRIPT_DIR/patches/0002-stateless-main-headless-signer.patch" 2>/dev/null); then
        (cd "$UPSTREAM_DIR" && git apply -R "$SCRIPT_DIR/patches/0002-stateless-main-headless-signer.patch")
        echo "    Reverted 0002-stateless-main-headless-signer.patch"
    else
        echo "    Patch 0002 not applied or already clean."
    fi

    echo "--> 2. Reverting manifest.py patch in builder root..."
    if (cd "$TARGET_DIR" && git apply -R --check "$SCRIPT_DIR/patches/0001-manifest-headless-signer.patch" 2>/dev/null); then
        (cd "$TARGET_DIR" && git apply -R "$SCRIPT_DIR/patches/0001-manifest-headless-signer.patch")
        echo "    Reverted 0001-manifest-headless-signer.patch"
    else
        echo "    Patch 0001 not applied or already clean."
    fi

    echo "--> 3. Restoring upstream manifest.py..."
    if [ -f "$MANIFEST_MOD" ] && [ -f "$MANIFEST_UPSTREAM" ]; then
        cp -v "$MANIFEST_MOD" "$MANIFEST_UPSTREAM"
    fi

    echo "--> 4. Removing staged headless fixture and runner files from frozen_app/..."
    rm -f "$TARGET_DIR/frozen_app/_headless_fixtures.py" "$TARGET_DIR/frozen_app/_headless_signer.py"

    echo "=== Phase 23 changes reverted cleanly ==="
    exit 0
fi

echo "--> 1. Staging headless fixture and runner into frozen_app/..."
mkdir -p "$TARGET_DIR/frozen_app"
cp -v "$SCRIPT_DIR/files/frozen_app/"* "$TARGET_DIR/frozen_app/"

echo "--> 2. Applying manifest.py patch in builder root..."
if (cd "$TARGET_DIR" && git apply --check "$SCRIPT_DIR/patches/0001-manifest-headless-signer.patch" 2>/dev/null); then
    (cd "$TARGET_DIR" && git apply "$SCRIPT_DIR/patches/0001-manifest-headless-signer.patch")
    echo "    Applied 0001-manifest-headless-signer.patch"
else
    echo "    Patch 0001 already applied or conflict."
fi

echo "--> 3. Syncing manifest.py into micropython upstream tree..."
if [ -f "$MANIFEST_MOD" ] && [ -d "$(dirname "$MANIFEST_UPSTREAM")" ]; then
    cp -v "$MANIFEST_MOD" "$MANIFEST_UPSTREAM"
fi

echo "--> 4. Applying main.c patch in micropython upstream..."
if (cd "$UPSTREAM_DIR" && git apply --check "$SCRIPT_DIR/patches/0002-stateless-main-headless-signer.patch" 2>/dev/null); then
    (cd "$UPSTREAM_DIR" && git apply "$SCRIPT_DIR/patches/0002-stateless-main-headless-signer.patch")
    echo "    Applied 0002-stateless-main-headless-signer.patch"
else
    echo "    Patch 0002 already applied or conflict."
fi

echo "=== Phase 23 changes applied successfully ==="
