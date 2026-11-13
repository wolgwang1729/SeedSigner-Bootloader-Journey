#!/bin/bash
# Phase 18 virtual_fb_demo: build + flash + monitor (reversible flash only).
# Never touches eFuses. Board: ESP32-P4-WIFI6-DEV-KIT, /dev/ttyACM0 @ 115200.
set -e
: "${ESPPORT:=/dev/ttyACM0}"
: "${ESPBAUD:=921600}"

if [ -f "$HOME/esp/esp-idf-v5.5/export.sh" ]; then
  # shellcheck disable=SC1090
  . "$HOME/esp/esp-idf-v5.5/export.sh"
elif [ -f "$HOME/esp/esp-idf/export.sh" ]; then
  # shellcheck disable=SC1090
  . "$HOME/esp/esp-idf/export.sh"
else
  echo "ERROR: ESP-IDF export.sh not found" >&2
  exit 1
fi

cd "$(dirname "$0")"
idf.py set-target esp32p4
idf.py build
idf.py -p "$ESPPORT" -b "$ESPBAUD" flash
idf.py -p "$ESPPORT" monitor
