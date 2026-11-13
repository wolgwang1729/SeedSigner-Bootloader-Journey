#!/usr/bin/env python3
"""Headless UART capture for the ESP32-P4 devkit (Phase 22 hardware runs).

`idf.py monitor` refuses to run without a TTY, so this is the plain-pyserial
equivalent: park DTR/RTS deasserted (normal boot), pulse RTS to reset through
the CH343 auto-reset circuit, then stream the console at the given baud into a
raw log file. Read-only with respect to flash and eFuses.

Examples:
    # Fresh reset + 120 s capture of the loader/payload chain:
    ./capture_serial.py --reset --seconds 120 -o Phase_22/logs/specter_hw_stateless_boot.txt
    # Attach without resetting (capture whatever is on the wire):
    ./capture_serial.py --seconds 30 -o /tmp/live.txt
"""

import argparse
import time

import serial


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=240,
                    help="capture window (default: 240)")
    ap.add_argument("--reset", action="store_true",
                    help="pulse RTS (EN) to reset the target before capturing")
    ap.add_argument("-o", "--output", required=True, help="raw log file")
    args = ap.parse_args()

    with serial.Serial(args.port, args.baud, timeout=0.2) as ser:
        ser.dtr = False   # GPIO0 high -> normal boot, never download mode
        ser.rts = False   # EN high
        if args.reset:
            time.sleep(0.2)
            ser.rts = True    # EN low
            time.sleep(0.15)
            ser.rts = False   # release -> boot
        deadline = time.monotonic() + args.seconds
        total = 0
        with open(args.output, "wb") as f:
            while time.monotonic() < deadline:
                data = ser.read(4096)
                if data:
                    f.write(data)
                    f.flush()
                    total += len(data)
    print(f"captured {total} bytes -> {args.output}")


if __name__ == "__main__":
    main()
