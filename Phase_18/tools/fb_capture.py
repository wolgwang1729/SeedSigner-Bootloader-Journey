#!/usr/bin/env python3
"""Phase 18 serial helper: talk to virtual_fb_demo without idf_monitor TTY pain.

Examples:
  fb_capture.py --cmds info --monitor-secs 12          # send 'info', capture 12 s
  fb_capture.py --dump --out dump.log                  # full framebuffer stream
  fb_capture.py --cmds help,save --monitor-secs 15     # interact + watch

Needs pyserial (present in the ESP-IDF python env, else: pip install pyserial).
Console baud is 115200 (CONFIG_ESP_CONSOLE_UART_BAUDRATE).
"""
import argparse
import os
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("ERROR: pyserial missing. Run inside the IDF env "
             "(. ~/esp/esp-idf-v5.5/export.sh) or: pip install pyserial")


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 18 demo serial helper")
    ap.add_argument("--port", default=os.environ.get("ESPPORT", "/dev/ttyACM0"))
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--cmds", default="", help="comma-separated console commands")
    ap.add_argument("--dump", action="store_true", help="send 'dump', capture to FB_END")
    ap.add_argument("--out", default="dump.log", help="capture file")
    ap.add_argument("--monitor-secs", type=float, default=10.0)
    ap.add_argument("--dump-timeout", type=float, default=200.0)
    a = ap.parse_args()

    s = serial.Serial(a.port, a.baud, timeout=1)
    s.reset_input_buffer()
    time.sleep(1.0)

    if a.cmds:
        for c in [c.strip() for c in a.cmds.split(",") if c.strip()]:
            s.write((c + "\n").encode())
            s.flush()
            print(f"[cap] sent: {c}", flush=True)
            time.sleep(2.0)

    t0 = time.time()
    chunks = 0
    if a.dump:
        s.write(b"dump\n")
        s.flush()
        print("[cap] sent: dump — reading until FB_END ...", flush=True)
        limit = a.dump_timeout
    else:
        limit = a.monitor_secs

    with open(a.out, "wb") as f:
        while time.time() - t0 < limit:
            d = s.read(8192)
            if d:
                f.write(d)
                f.flush()
                if a.dump:
                    t = d.decode("utf-8", "replace")
                    chunks += t.count("FB_CHUNK")
                    if chunks and chunks % 1000 == 0:
                        print(f"[cap] ... {chunks} chunks", flush=True)
                    if "FB_END" in t:
                        break
        if a.dump and "FB_END" not in locals().get("t", ""):
            # re-check tail of file for FB_END (split-read safety)
            with open(a.out, "rb") as f:
                tail = f.read()[-200:].decode("utf-8", "replace")
            if "FB_END" not in tail:
                print("[cap] TIMEOUT waiting for FB_END", flush=True)
                return 1
    print(f"[cap] wrote {a.out}" + (f" ({chunks} FB_CHUNK seen)" if a.dump else ""),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
