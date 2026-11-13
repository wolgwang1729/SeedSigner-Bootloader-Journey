#!/usr/bin/env python3
"""Phase 19 follow-up — host side of the cold power-cycle canary check.

Used against the board's UART bridge (which stays enumerated across devkit
power cuts), so one `log` process can capture the entire campaign:

  log   — timestamped, flush-per-chunk capture of everything the loader /
          payload prints. Single reader; keep it running for the whole run.
          Writes `<out>` (timestamped) and `<out>.raw` (clean bytes).
          With `--cmd-fifo`, also injects CR-terminated command lines into
          the REPL, so this process is the ONLY port user for the whole
          session (no reopen DTR/RTS glitches on ESP auto-reset circuits).
          Injected lines are recorded in the capture as `[host] send: ...`.
  send  — write-only send of one CR-terminated command line (fallback for
          one-shot use when no `log` process is running). CR is what the
          IDF console line discipline consumes (Phase 21 finding).

Open policy: DTR/RTS are deasserted right after open — ESP auto-reset
circuits treat asserted lines as reset/bootloader requests.

Procedure (see Phase_19_Runtime_Sanitization_Glitch.md §10):
  1. mkfifo /tmp/opencode/pc_cmd
     python3 power_canary_check.py log --cmd-fifo /tmp/opencode/pc_cmd \
         --out logs/powercycle_session.txt &
  2. echo plant > /tmp/opencode/pc_cmd          # wait for CANARY_PLANTED
  3. cut devkit power, wait, re-plug             # cold boot
  4. read the INSPECT verdict from the capture (reason=poweron/brownout)

Mock pattern only — never a real seed. No eFuse action.
"""
import argparse
import datetime as dt
import os
import sys
import time

import serial


def _open(port: str, baud: int, timeout: float) -> serial.Serial:
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = timeout
    s.dsrdtr = False
    s.rtscts = False
    s.open()
    try:
        s.dtr = False
        s.rts = False
    except Exception:
        pass  # bridge without control lines
    return s


def mode_log(args) -> int:
    raw_path = os.path.splitext(args.out)[0] + ".raw"
    s = _open(args.port, args.baud, 0.05)
    ts_file = open(args.out, "ab", buffering=0)
    raw_file = open(raw_path, "ab", buffering=0)
    fifo_fd = None
    if args.cmd_fifo:
        try:
            os.mkfifo(args.cmd_fifo)
        except FileExistsError:
            pass
        # O_RDWR keeps a writer end open so the reader never sees EOF.
        fifo_fd = os.open(args.cmd_fifo, os.O_RDWR | os.O_NONBLOCK)
    print(f"[log] {args.port}@{args.baud} -> {args.out} (+ {raw_path})"
          f"{f'; cmd fifo: {args.cmd_fifo}' if fifo_fd is not None else ''}"
          "; ctrl-c to stop", flush=True)
    def _stamp() -> str:
        return dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]

    try:
        while True:
            if fifo_fd is not None:
                try:
                    blob = os.read(fifo_fd, 512)
                except BlockingIOError:
                    blob = b""
                for line in blob.replace(b"\r", b"\n").split(b"\n"):
                    line = line.strip()
                    if not line:
                        continue
                    note = ""
                    try:
                        s.write(line + b"\r")
                        s.flush()
                    except (serial.SerialException, OSError) as e:
                        note = f" (FAILED: {e})"
                    ts_file.write(
                        f"[{_stamp()}] [host] send: "
                        f"{line.decode(errors='replace')}{note}\n".encode())
            try:
                data = s.read(4096)
            except (serial.SerialException, OSError) as e:
                # Port lost (bridge re-enumerated, cable moved, ...): reopen
                # and keep capturing. The canary lives in board RAM, not in
                # this process, and a host reopen cannot un-power the board
                # (only a possible DTR glitch reset, which is logged).
                ts_file.write(f"[{_stamp()}] [host] port error: {e!r}; reopening\n".encode())
                try:
                    s.close()
                except Exception:
                    pass
                while True:
                    try:
                        s = _open(args.port, args.baud, 0.05)
                        break
                    except Exception:
                        time.sleep(0.5)
                ts_file.write(f"[{_stamp()}] [host] port reopened\n".encode())
                continue
            if not data:
                continue
            ts_file.write(f"[{_stamp()}] ".encode() + data)
            raw_file.write(data)
    except KeyboardInterrupt:
        pass
    finally:
        ts_file.close()
        raw_file.close()
        s.close()
    return 0


def mode_send(args) -> int:
    s = _open(args.port, args.baud, 0)
    time.sleep(0.05)
    s.write(args.cmd.encode() + b"\r")
    s.flush()
    s.close()
    print(f"[send] {args.cmd!r}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["log", "send"])
    ap.add_argument("cmd", nargs="?", help="command line (send mode)")
    ap.add_argument("--port", default="/dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", default="logs/powercycle_session.txt",
                    help="log mode output path (timestamped; .raw alongside)")
    ap.add_argument("--cmd-fifo",
                    help="log mode: FIFO path; each line written to it is "
                         "sent to the board as a CR-terminated command")
    a = ap.parse_args()
    if a.mode == "send":
        if not a.cmd:
            ap.error("send mode needs a command")
        return mode_send(a)
    return mode_log(a)


if __name__ == "__main__":
    sys.exit(main())
