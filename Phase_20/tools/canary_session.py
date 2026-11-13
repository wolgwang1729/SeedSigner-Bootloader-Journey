#!/usr/bin/env python3
"""Phase 20 serial session driver - headless canary/R-route campaign helper.

Opens /dev/ttyACM0 @ 115200, syncs to the canary `> ` prompt (resetting the
board only if nothing arrives - a plain reboot, fully reversible), sends
newline-terminated commands, and saves a timestamped transcript to
Phase_20/logs/.

Usage:
    python3 tools/canary_session.py status selftest
    python3 tools/canary_session.py --tag r0-control scrub_off plant fault_restart
    python3 tools/canary_session.py --tag r0-patched scrub_on plant fault_restart
    python3 tools/canary_session.py --tag r0-status --cmds status

After a fault_* command the driver keeps reading through the reboot
(loader INSPECT/JMP lines + payload re-boot) until the next `> ` prompt.

Safety: serial reads/writes + RTS/DTR reset pulses only. No flash writes,
no eFuse operations of any kind.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

import serial

PORT = "/dev/ttyACM0"
BAUD = 115200
# The canary REPL prompt. Must be newline-anchored: loader image-plan lines
# contain `-> ` mid-line (e.g. `-> fake_flash+0x20020`), which a bare `> `
# needle falsely matches, cutting reboot captures short.
PROMPT_RE = re.compile(rb"\n> ")
LOGDIR = Path(__file__).resolve().parent.parent / "logs"

ANSI = re.compile(rb"\x1b\[[0-9;]*m")


def clean(raw: bytes) -> bytes:
    return ANSI.sub(b"", raw)


def has_prompt(buf: bytes) -> bool:
    return PROMPT_RE.search(clean(buf)) is not None


def esptool_reset() -> None:
    # Hard reset via esptool (same path as the proven chip_id run).
    # Fully reversible reboot - no flash, no eFuse contact.
    subprocess.run(
        [sys.executable, "-m", "esptool", "--port", PORT,
         "--baud", "921600", "run"],
        capture_output=True, timeout=90,
    )


def read_until(buf: bytearray, ser, timeout: float) -> bytes:
    end = time.time() + timeout
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf.extend(ser.read(n))
            if has_prompt(bytes(buf)):
                return bytes(buf)
        time.sleep(0.05)
    return bytes(buf)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("cmds", nargs="*", help="commands to send in order")
    ap.add_argument("--tag", default="session")
    ap.add_argument("--cmds-file", default=None)
    ap.add_argument("--sync-timeout", type=float, default=20.0)
    ap.add_argument("--cmd-timeout", type=float, default=15.0)
    ap.add_argument("--reboot-timeout", type=float, default=40.0)
    args = ap.parse_args()

    cmds = list(args.cmds)
    if args.cmds_file:
        cmds += Path(args.cmds_file).read_text().split()

    LOGDIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    logpath = LOGDIR / f"exp_{args.tag}_{stamp}.log"
    logf = open(logpath, "wb")

    def emit(raw: bytes):
        logf.write(raw)
        logf.flush()
        sys.stdout.buffer.write(clean(raw))
        sys.stdout.buffer.flush()

    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    time.sleep(0.3)
    buf = bytearray()

    # --- sync: passive peek, then poke, then esptool reset -----------------
    # (The canary REPL prints `> ` once and idles - passive waiting alone
    # deadlocks against an already-idle board, so poke it with newline.)
    out = read_until(buf, ser, 5.0)
    if not has_prompt(out):
        buf.clear()
        ser.write(b"\n")
        out = read_until(buf, ser, 8.0)
    if not has_prompt(out):
        emit(b"SYNC: idle board unresponsive - esptool hard reset\n")
        buf.clear()
        ser.close()
        esptool_reset()
        ser.open()
        time.sleep(0.5)
        out = read_until(buf, ser, args.reboot_timeout + 20)
        if not has_prompt(out):
            emit(bytes(buf))
            emit(b"\n[driver] SYNC FAILED - see log\n")
            print(f"\nLOG: {logpath}", flush=True)
            return 2
    emit(f"\n[driver] synced, transcript: {logpath}\n".encode())
    emit(bytes(buf))
    buf.clear()

    # --- command loop ------------------------------------------------------
    for cmd in cmds:
        emit(f"\n[driver] >>> {cmd}\n".encode())
        buf.clear()
        ser.write((cmd + "\n").encode())
        is_fault = cmd.startswith("fault_")
        out = read_until(
            buf, ser,
            args.reboot_timeout if is_fault else args.cmd_timeout,
        )
        emit(bytes(buf))
        emit(b"\n[driver] --- chunk end ---\n")
        if not has_prompt(out):
            emit(f"[driver] WARNING: no prompt after '{cmd}' (timeout)\n".encode())
            if is_fault:
                print(f"\nLOG: {logpath}", flush=True)
                return 3
    print(f"\nLOG: {logpath}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
