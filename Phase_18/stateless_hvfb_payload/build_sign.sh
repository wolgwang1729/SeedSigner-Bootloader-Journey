#!/usr/bin/env bash
# ==============================================================================
# Build & Sign Stateless-HVFB Payload — Phase 18, slice 1
# Target  : ESP32-P4 stateless secure loader (desktop repo, test keys)
# Payload : stateless_hvfb_payload (LVGL virtual display + emulated touch,
#           PSRAM XIP via components/stateless_shim)
# Output  : Phase_18/build/seedsigner_esp32p4.bin → push with the loader's
#           RAM-only SD uploader (no card ejection):
#             ~/Desktop/seedsigner-esp32-bootloader/run.sh --target esp32p4 \
#               upload-sd Phase_18/build/seedsigner_esp32p4.bin
# ==============================================================================
set -uo pipefail

log_info()    { echo -e "\033[1;34m[INFO]\033[0m $*"; }
log_success() { echo -e "\033[1;32m[PASS]\033[0m $*"; }
log_warn()    { echo -e "\033[1;33m[WARN]\033[0m $*" >&2; }
log_error()   { echo -e "\033[1;31m[FAIL]\033[0m $*" >&2; }
log_step()    { echo -e "\n\033[1;35m=== $* ===\033[0m"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PHASE18_DIR="$(dirname "$SCRIPT_DIR")"
LOADER_DIR="$HOME/Desktop/seedsigner-esp32-bootloader"

if ! command -v idf.py >/dev/null 2>&1; then
    log_info "idf.py not in PATH — sourcing ESP-IDF..."
    for candidate in \
        "$HOME/esp/esp-idf-v5.5/export.sh" \
        "$HOME/esp/esp-idf/export.sh"; do
        [ -f "$candidate" ] && { . "$candidate" >/dev/null 2>&1 || true; break; }
    done
fi
if ! command -v idf.py >/dev/null 2>&1; then
    log_error "idf.py not found. Source ESP-IDF export.sh first."
    exit 1
fi

log_step "Step 1: Build payload (PSRAM XIP, stateless shim entry)"
( cd "$SCRIPT_DIR" && idf.py set-target esp32p4 && idf.py build )

RAW_PAYLOAD_BIN=$(find "$SCRIPT_DIR/build" -maxdepth 1 -name "*.bin" \
    ! -name "bootloader.bin" ! -name "partition-table.bin" | head -1)
if [ -z "$RAW_PAYLOAD_BIN" ] || [ ! -s "$RAW_PAYLOAD_BIN" ]; then
    log_error "Payload binary not found under $SCRIPT_DIR/build"
    exit 1
fi
log_success "Payload binary: $RAW_PAYLOAD_BIN"

log_step "Step 2: Sign payload (Specter bundle, test profile)"
SIGN_TOOL="$LOADER_DIR/tools/generate_signed_payload.py"
if [ ! -f "$SIGN_TOOL" ]; then
    log_error "Signing tool not found: $SIGN_TOOL"
    exit 1
fi
mkdir -p "$PHASE18_DIR/build"
SIGNED_PAYLOAD_BIN="$PHASE18_DIR/build/seedsigner_esp32p4.bin"
python3 "$SIGN_TOOL" --platform seedsigner_esp32p4 --profile test \
    "$RAW_PAYLOAD_BIN" "$SIGNED_PAYLOAD_BIN" || {
    log_error "Signing failed (need python3 ecdsa + bech32 packages)."
    exit 1
}
if [ ! -s "$SIGNED_PAYLOAD_BIN" ]; then
    log_error "Signed payload not produced."
    exit 1
fi
log_success "Signed payload: $SIGNED_PAYLOAD_BIN ($(wc -c < "$SIGNED_PAYLOAD_BIN") bytes)"
log_warn "Push to SD without ejecting the card:"
log_warn "  $LOADER_DIR/run.sh --target esp32p4 upload-sd $SIGNED_PAYLOAD_BIN"
log_warn "Then talk to it (115200 baud): python3 $PHASE18_DIR/tools/fb_live.py --baud 115200"
