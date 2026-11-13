#!/usr/bin/env python3
"""Phase 20 R6 tear injector: kill an SD upload mid-stream (power-loss sim).

Streams <local> to <sd_name> via the RAM uploader, then SIGKILLs the host
uploader at --kill-at bytes - no ABORT, no COMMIT, no graceful close,
exactly like a power cut. The device keeps whatever hit the card.

  python3 tools/tear_upload.py attacks/badsig.bin --kill-at 100000

Exit 42 when the tear landed (kill sent mid-stream). All SD/flash effects
are the experiment; no eFuse contact.
"""
import argparse
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

LOADER_REPO = Path(os.environ.get("LOADER_REPO", str(Path.home() / "Desktop" / "seedsigner-esp32-bootloader")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("local_file")
    ap.add_argument("--name", default="seedsigner_esp32p4.bin")
    ap.add_argument("--kill-at", type=int, default=100000)
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", default="921600")
    args = ap.parse_args()

    cmd = [sys.executable, str(LOADER_REPO / "tools" / "sd_upload.py"),
           "--chip", "esp32p4", "--port", args.port, "--baud", args.baud,
           "--uploader-bin", str(LOADER_REPO / "uploader" / "build" / "esp32p4" /
                                 "seedsigner_sd_uploader.bin"),
           "upload", args.local_file, "--name", args.name]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    max_seen = 0
    torn = False
    assert p.stdout is not None
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        for m in re.finditer(r"\[(\d+)/\d+ bytes", line):
            max_seen = max(max_seen, int(m.group(1)))
            if max_seen >= args.kill_at and not torn:
                p.send_signal(signal.SIGKILL)
                torn = True
                print(f"\n[tear] host SIGKILLed at {max_seen} streamed bytes")
                break
        if torn:
            break
    p.wait(timeout=60)
    # Drain anything left without blocking forever.
    end = time.time() + 3
    while time.time() < end:
        line = p.stdout.readline()
        if not line:
            break
        sys.stdout.write(line)
    print(f"[tear] max_streamed={max_seen} host_rc={p.returncode}")
    return 42 if torn else 10


if __name__ == "__main__":
    raise SystemExit(main())
