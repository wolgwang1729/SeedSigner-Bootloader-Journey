#!/usr/bin/env python3
"""Raw boot capture: reset via esptool, dump 25s of UART to stdout."""
import subprocess
import sys
import time

import serial

PORT = "/dev/ttyACM0"
SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0

subprocess.run(
    [sys.executable, "-m", "esptool", "--port", PORT, "--baud", "921600", "run"],
    capture_output=True, timeout=90,
)
ser = serial.Serial(PORT, 115200, timeout=0.1)
time.sleep(0.5)
end = time.time() + SECS
while time.time() < end:
    n = ser.in_waiting
    if n:
        sys.stdout.buffer.write(ser.read(n))
        sys.stdout.buffer.flush()
    time.sleep(0.05)
