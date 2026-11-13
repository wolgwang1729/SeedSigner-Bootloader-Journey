#!/usr/bin/env bash
# ==============================================================================
# run_p4_stateless_sign.sh - End-to-end headless PSBT signing verification on
# ESP32-P4 under stateless PSRAM execution.
#
# Steps:
#   1. Signs the MicroPython payload with Specter secp256k1 key and merges it
#      into the headless emulator flash image (/tmp/emu_ci/emu_p4.bin).
#   2. Boots emu_p4.bin in esp-emu (v0.50.0, rev 1.3 route: rev0 ROM + virtual
#      rev1.3 eFuse blob).
#   3. Emits UART stream until '[P23] SUCCESS' is reached.
#   4. Verifies the emitted UR2 crypto-psbt frames with verify_signed_psbt.py.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PHASE_DIR/logs"
LOG_FILE="$LOG_DIR/p4_emu_stateless_sign.txt"

LOADER_ROOT="${LOADER_ROOT:-$HOME/Desktop/seedsigner-esp32-bootloader}"
PAYLOAD_BIN="${PAYLOAD_BIN:-$HOME/Desktop/seedsigner-micropython-builder-upstream/build/WAVESHARE_ESP32_P4_WIFI6_TOUCH_LCD_43-PRE_REV3_STATELESS/micropython.bin}"
SCRATCH="${SCRATCH:-/tmp/emu_ci}"
TIMEOUT="${TIMEOUT:-300s}"

ROM_ELF="${P4_REV0_ROM:-$HOME/.espressif/tools/esp-rom-elfs/20241011/esp32p4_rev0_rom.elf}"
[ -f "$ROM_ELF" ] || ROM_ELF="$(find "$HOME/.espressif/tools/esp-rom-elfs" -name "esp32p4_rev0_rom.elf" 2>/dev/null | head -n1)"

mkdir -p "$LOG_DIR"

echo "=== Phase 23 Slice A: Headless PSBT Signing Verification ==="
echo "Bootloader: $LOADER_ROOT"
echo "Payload:    $PAYLOAD_BIN"
echo "ROM ELF:    $ROM_ELF"
echo "Log file:   $LOG_FILE"

if [ ! -f "$PAYLOAD_BIN" ]; then
    echo "ERROR: Payload binary not found: $PAYLOAD_BIN" >&2
    exit 1
fi

if [ ! -f "$ROM_ELF" ]; then
    echo "ERROR: esp32p4 rev0 ROM ELF not found" >&2
    exit 1
fi

# 1. Build and sign emulator image via loader CI script
echo "--> 1. Building and signing emulator image via loader CI script..."
PAYLOAD_BIN="$PAYLOAD_BIN" SCRATCH="$SCRATCH" "$LOADER_ROOT/tools/emu/run_emu_ci.sh" build p4

EMU_BIN="$SCRATCH/emu_p4.bin"
EFUSE_BLOB="$SCRATCH/efuse_p4_rev1.3.bin"

if [ ! -f "$EMU_BIN" ] || [ ! -f "$EFUSE_BLOB" ]; then
    echo "ERROR: Expected build artifacts missing in $SCRATCH" >&2
    exit 1
fi

# 2. Boot in esp-emu
echo "--> 2. Booting in esp-emu (rev-1.3 route)..."
# Pass --exit-on to terminate emulator when signing completes successfully
esp-emu \
    --chip esp32p4 \
    --firmware "$EMU_BIN" \
    --rom "$ROM_ELF" \
    --efuse "$EFUSE_BLOB" \
    --psram-size 32M \
    --timeout "$TIMEOUT" \
    --exit-on "[P23] SUCCESS" \
    | tee "$LOG_FILE"

# 3. Verify signed PSBT frames
echo "--> 3. Verifying signed PSBT with host verification script..."
python3 "$SCRIPT_DIR/verify_signed_psbt.py" "$LOG_FILE"

echo "=== Phase 23 Slice A: VERIFIED SUCCESSFUL ==="
