#!/usr/bin/env python3
"""Phase 18 live screen emulator: a desktop window for the DEV-KIT virtual FB.

Board side (unchanged): virtual_fb_demo streams
  FB_BEGIN <w> <h> <len> <crc>
  FB_CHUNK <seq> <base64(192 raw bytes)>
  FB_END <count>
over the console UART (default 115200, see sdkconfig.defaults).

This tool:
  - opens the serial port, sends `dump`,
  - reassembles the 480x800 RGB565LE frame live,
  - paints each display row into a tkinter window as soon as its
    firmware rows arrive (progressive scanline update, 2x downscale),
  - lets you type console commands (info/help/save/clear/dump) from the GUI,
  - optionally loops (emulator feel) and saves each frame as PNG.

Degraded-mode only: the physical LCD stays dark; this window IS the screen.
Do not claim panel/DSI/camera success from this tool.

Deps: pyserial + tkinter (stdlib). Headless mode (--no-show) needs no display.

Examples:
  python3 fb_live.py                        # live window, loops frames
  python3 fb_live.py --once --out fb0.png   # single frame + save + exit
  python3 fb_live.py --no-show --once       # headless capture (CI-safe)
  python3 fb_live.py --selftest --show      # no hardware: animate test frames
"""
import argparse
import base64
import binascii
import os
import queue
import re
import sys
import threading
import time

W = 480
H = 800
FRAME_LEN = W * H * 2
CHUNK_RAW = 192
CHUNKS_PER_FW_ROW = (W * 2) // CHUNK_RAW  # 960/192 = 5 (portrait; landscape rows straddle)
NCHUNKS = FRAME_LEN // CHUNK_RAW          # 4000 (both supported geometries)

try:
    import fb_viewer  # reuse RGB565->RGB888 + PNG writer
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fb_viewer


# ---------- pure helpers (hardware-free, unit-tested) ----------

def _tail_token(line: str, marker: str):
    """Return substring starting at marker, tolerating monitor prefixes."""
    i = line.find(marker)
    if i < 0:
        return None
    return line[i:]


def parse_fb_begin(line: str):
    t = _tail_token(line, "FB_BEGIN")
    if t is None:
        return None
    try:
        _, w, h, ln, crc = t.split()
        return {"w": int(w), "h": int(h), "len": int(ln), "crc": crc.upper()}
    except (ValueError, IndexError):
        return None


def parse_fb_chunk(line: str):
    t = _tail_token(line, "FB_CHUNK")
    if t is None:
        return None, None
    try:
        _, seq, b64 = t.split(None, 2)
        return int(seq), base64.b64decode(b64)
    except (ValueError, IndexError, base64.binascii.Error):
        return None, None


def parse_fb_end(line: str):
    t = _tail_token(line, "FB_END")
    if t is None:
        return None
    try:
        return int(t.split()[1])
    except (ValueError, IndexError):
        return None


# ---------- defragmenting stream parser (hardware-free, unit-tested) ----------
#
# The UART stream is printed by several firmware tasks sharing one console
# with no mutual exclusion. A `[HVFB] tap …` confirmation (or app print) can
# land mid-chunk-line, and at high baud the bridge can drop bytes, gluing or
# splitting lines. A strict line parser then loses the whole frame. This
# parser instead scans the byte stream for headers and reassembles payloads:
# every chunk carries exactly CHUNK_PAYLOAD_B64 base64 chars, and base64 has
# no spaces/brackets — so anything that is not pure base64 is a log line to
# skip. Unrecoverable loss still ends in CRC-MISMATCH downstream (correct).

CHUNK_PAYLOAD_B64 = 256  # 192 raw bytes -> 256 base64 chars, all chunks/frames

_BEGIN_RE = re.compile(r"FB_BEGIN\s+(\d+)\s+(\d+)\s+(\d+)\s+([0-9A-Fa-f]{8})(?=FB_BEGIN|FB_CHUNK|FB_END|[^0-9A-Fa-f]|$)")
_END_RE = re.compile(r"FB_END\s+(\d+)")
_CHUNK_RE = re.compile(r"FB_CHUNK\s+(\d+)\s+")
_B64LINE_RE = re.compile(r"[A-Za-z0-9+/=]+")


class StreamParser:
    """Reassembles (begin/chunk/end/log) events from a possibly torn stream.

    Feed it raw decoded text (newlines preserved); it returns event lists.
    Unconsumable bytes are held for more data, never silently dropped except
    orphan base64 runs between frames. Event shapes match the old line
    parser: ("begin", meta), ("chunk", seq, bytes), ("end", count),
    ("log", msg).
    """

    def __init__(self):
        self.buf = ""
        self.pending_seq = None
        self.pending_parts = []
        self.pending_need = 0

    def feed(self, text: str):
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if text:
            self.buf += text
        events = []
        while True:
            if self.pending_seq is None:
                if not self._pump_header(events):
                    break
            else:
                if not self._pump_payload(events):
                    break
        return events

    @staticmethod
    def _emit_log(events, line: str):
        s = line.strip()
        if not s:
            return
        if _B64LINE_RE.fullmatch(s):
            return  # orphan base64 between frames: drop silently
        events.append(("log", s[-120:]))

    def _pump_header(self, events) -> bool:
        ms = [(m.start(), "begin", m) for m in [_BEGIN_RE.search(self.buf)] if m]
        ms += [(m.start(), "chunk", m) for m in [_CHUNK_RE.search(self.buf)] if m]
        ms += [(m.start(), "end", m) for m in [_END_RE.search(self.buf)] if m]
        if not ms:
            if "\n" in self.buf:
                *lines, tail = self.buf.split("\n")
                for line in lines:
                    self._emit_log(events, line)
                self.buf = tail
                return True
            return False
        ms.sort(key=lambda t: t[0])
        pos, kind, m = ms[0]
        for line in self.buf[:pos].split("\n"):
            self._emit_log(events, line)
        self.buf = self.buf[m.end():]
        if kind == "begin":
            w, h, ln, crc = m.groups()
            events.append(("begin", {"w": int(w), "h": int(h),
                                     "len": int(ln), "crc": crc.upper()}))
        elif kind == "end":
            events.append(("end", int(m.group(1))))
        else:
            self.pending_seq = int(m.group(1))
            self.pending_parts = []
            self.pending_need = CHUNK_PAYLOAD_B64
        return True

    def _abandon_pending(self):
        self.pending_seq = None
        self.pending_parts = []
        self.pending_need = 0

    def _pump_payload(self, events) -> bool:
        pos = 0
        n = len(self.buf)
        progressed = False
        while self.pending_need > 0:
            # Fast path: the needed payload sits contiguously ahead (clean
            # single-line chunk, or newlines lost to overrun). Pure-base64
            # runs can never be headers or log lines, so take them whole.
            window = self.buf[pos:pos + self.pending_need]
            if (len(window) == self.pending_need and "\n" not in window
                    and _B64LINE_RE.fullmatch(window)):
                self.pending_parts.append(window)
                self.pending_need = 0
                pos += len(window)
                progressed = True
                continue
            nl = self.buf.find("\n", pos)
            if nl == -1:
                tail = self.buf[pos:]
                if (_BEGIN_RE.search(tail) or _END_RE.search(tail)
                        or _CHUNK_RE.search(tail)):
                    self._abandon_pending()
                    self.buf = self.buf[pos:]
                    return True
                break  # hold partial tail for more data
            line = self.buf[pos:nl]
            if (_BEGIN_RE.search(line) or _END_RE.search(line)
                    or _CHUNK_RE.search(line)):
                self._abandon_pending()
                self.buf = self.buf[pos:]
                return True
            s = line.strip()
            if not s:
                # Blank / whitespace-only line inside a chunk split
                # (extra newline from concurrent prints or stray CR).
                # Old line parser skipped these; without this the
                # while-loop below never advances pos and hangs the
                # reader thread (frozen window). Skip and continue.
                pos = nl + 1
                progressed = True
                continue
            if s and not _B64LINE_RE.fullmatch(s):
                events.append(("log", s[-120:]))
                progressed = True
                pos = nl + 1
            elif s:
                take = min(len(s), self.pending_need)
                self.pending_parts.append(s[:take])
                self.pending_need -= take
                progressed = True
                if take < len(s):
                    # Overshoot (glued lines): remainder is new content.
                    self.buf = s[take:] + self.buf[nl:]
                    pos = 0
                else:
                    pos = nl + 1
        if self.pending_need == 0:
            try:
                data = base64.b64decode("".join(self.pending_parts))
            except base64.binascii.Error:
                events.append(("log", f"chunk {self.pending_seq} b64 error"))
                data = b""
            seq = self.pending_seq
            self._abandon_pending()
            self.buf = self.buf[pos:]
            events.append(("chunk", seq, data))
            return True
        if progressed:
            self.buf = self.buf[pos:]
        return progressed


# ---------- touch emulation (window click -> serial `tap`/`swipe`) ----------
#
# Device side (board_common HEADLESS_VIRTUAL_FB draft): a pointer-type lv_indev
# fed by console lines `tap <x> <y>` (press+release pulse) and
# `swipe <x0> <y0> <x1> <y1>` (press/move/release). Coordinates are firmware
# framebuffer pixels (480x800 portrait, top-left origin) — the same space the
# GT911 reports on the real 4.3" panel, so apps need no headless special case.

TAP_SLOP_PX = 8  # display-px drag distance below which a click is a tap

# Coordinate ceiling for the host-side tap/swipe parser mirrors: union of both
# supported geometries (portrait 480x800, landscape 800x480).
MAX_COORD = 800


def clamp_int(v, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def display_to_fw(x_disp, y_disp, scale: int = 2, w: int = W, h: int = H):
    """Window pixel -> firmware framebuffer pixel (nearest-neighbour, clamped)."""
    return (clamp_int(x_disp * scale, 0, w - 1),
            clamp_int(y_disp * scale, 0, h - 1))


def format_tap(fw_x, fw_y, w: int = W, h: int = H) -> str:
    return f"tap {clamp_int(fw_x, 0, w - 1)} {clamp_int(fw_y, 0, h - 1)}"


def format_swipe(fw_x0, fw_y0, fw_x1, fw_y1, w: int = W, h: int = H) -> str:
    return (f"swipe {clamp_int(fw_x0, 0, w - 1)} {clamp_int(fw_y0, 0, h - 1)} "
            f"{clamp_int(fw_x1, 0, w - 1)} {clamp_int(fw_y1, 0, h - 1)}")


def parse_tap_line(line: str):
    """Mirror of the device parser. Returns (x, y) or None."""
    t = _tail_token(line.strip(), "tap")
    if t is None:
        return None
    try:
        parts = t.split()
        if parts[0] != "tap" or len(parts) != 3:
            return None
        x, y = int(parts[1]), int(parts[2])
    except (ValueError, IndexError):
        return None
    if not (0 <= x < MAX_COORD and 0 <= y < MAX_COORD):
        return None
    return (x, y)


def parse_swipe_line(line: str):
    """Mirror of the device parser. Returns (x0, y0, x1, y1) or None."""
    t = _tail_token(line.strip(), "swipe")
    if t is None:
        return None
    try:
        parts = t.split()
        if parts[0] != "swipe" or len(parts) != 5:
            return None
        x0, y0, x1, y1 = (int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4]))
    except (ValueError, IndexError):
        return None
    if not (0 <= x0 < MAX_COORD and 0 <= y0 < MAX_COORD
            and 0 <= x1 < MAX_COORD and 0 <= y1 < MAX_COORD):
        return None
    return (x0, y0, x1, y1)


def rgb565le_pixel(raw: bytes, x: int, y: int, w: int = W):
    """Single pixel as (r,g,b) 8-bit. Raises IndexError out of bounds."""
    o = (y * w + x) * 2
    px = raw[o] | (raw[o + 1] << 8)
    return (((px >> 11) & 0x1F) * 255 // 31,
            ((px >> 5) & 0x3F) * 255 // 63,
            (px & 0x1F) * 255 // 31)


def display_row_hex(raw: bytes, y_disp: int, scale: int = 2, w: int = W, h: int = H) -> str:
    """One tkinter PhotoImage row string for display row y_disp.

    Nearest-neighbour downscale: firmware pixel (x*scale, y_disp*scale).
    Returns space-separated '#rrggbb' tokens (w//scale entries).
    """
    sw = w // scale
    y_fw = y_disp * scale
    parts = []
    for x_disp in range(sw):
        r, g, b = rgb565le_pixel(raw, x_disp * scale, y_fw, w)
        parts.append("#%02x%02x%02x" % (r, g, b))
    return " ".join(parts)


class LiveFrame:
    """Reassembly buffer for one UART-streamed frame (either geometry)."""

    def __init__(self, scale: int = 2):
        self.scale = scale
        self.w = W
        self.h = H
        self.frame_len = FRAME_LEN
        self.nchunks = NCHUNKS
        self.raw = bytearray(FRAME_LEN)
        self.received = bytearray(NCHUNKS)  # 0/1 per seq
        self.n_received = 0
        self.meta = {}
        self.done = False

    def reset(self, meta) -> bool:
        """Start a new frame. Returns False for unsupported geometry."""
        try:
            fb_viewer.check_geometry(meta["w"], meta["h"], meta["len"])
        except (ValueError, KeyError, TypeError):
            return False
        self.w = meta["w"]
        self.h = meta["h"]
        self.frame_len = self.w * self.h * 2
        self.nchunks = self.frame_len // CHUNK_RAW
        self.raw = bytearray(self.frame_len)
        self.received = bytearray(self.nchunks)
        self.n_received = 0
        self.meta = dict(meta or {})
        self.done = False
        return True

    def _row_complete(self, r: int) -> bool:
        """All bytes of firmware row r received (handles chunk straddling:
        800px rows are 1600 B = 8 1/3 chunks)."""
        rowlen = self.w * 2
        s0 = (r * rowlen) // CHUNK_RAW
        s1 = ((r + 1) * rowlen - 1) // CHUNK_RAW
        return all(self.received[s] for s in range(s0, s1 + 1))

    def apply_chunk(self, seq: int, data: bytes):
        """Store chunk; return list of newly-completed display rows (may be [])."""
        if seq is None or data is None:
            return []
        if not (0 <= seq < self.nchunks):
            return []
        if len(data) != CHUNK_RAW:
            # Protocol uses fixed 192B chunks (both geometries divide evenly).
            return []
        off = seq * CHUNK_RAW
        if off + len(data) > self.frame_len:
            return []
        if not self.received[seq]:
            self.received[seq] = 1
            self.n_received += 1
        self.raw[off:off + len(data)] = data
        rowlen = self.w * 2
        r0 = off // rowlen
        r1 = (off + len(data) - 1) // rowlen
        rows = []
        for fw_row in range(r0, r1 + 1):
            if fw_row % self.scale != 0:
                continue
            if self._row_complete(fw_row):
                rows.append(fw_row // self.scale)
        return rows

    def display_rows(self) -> int:
        return self.h // self.scale

    def is_complete(self) -> bool:
        return self.n_received >= self.nchunks

    def crc_hex(self) -> str:
        return "%08X" % (binascii.crc32(bytes(self.raw)) & 0xFFFFFFFF)

    def crc_ok(self) -> bool:
        want = (self.meta.get("crc") or "").upper()
        return bool(want) and self.crc_hex() == want


# ---------- serial reader (background thread) ----------

def reader_thread(ser, frame: LiveFrame, evq: queue.Queue, stop: threading.Event,
                  request_dump: threading.Event, log_fn=print):
    """Read lines forever; feed evq with ('begin'|'chunk'|'end'|'log', ...).

    Main thread sets request_dump to ask for a new `dump`. This thread owns
    all blocking reads; GUI writes (commands) go through ser.write directly
    under ser_lock.
    """
    buf_pending_dump = True  # first frame starts immediately
    parser = StreamParser()
    while not stop.is_set():
        if request_dump.is_set() or buf_pending_dump:
            request_dump.clear()
            buf_pending_dump = False
            try:
                ser.reset_input_buffer()
                ser.write(b"dump\n")
                ser.flush()
                evq.put(("log", "sent: dump"))
            except Exception as e:  # noqa: BLE001 - report then retry
                evq.put(("log", f"serial write failed: {e}"))
                time.sleep(1.0)
                continue
        try:
            raw = ser.readline()
        except Exception as e:  # noqa: BLE001
            evq.put(("log", f"serial read failed: {e}"))
            time.sleep(0.5)
            continue
        if not raw:
            continue
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        if not text:
            continue
        for ev in parser.feed(text):
            kind = ev[0]
            if kind == "begin":
                meta = ev[1]
                if frame.reset(meta):
                    evq.put(("begin", dict(meta)))
                else:
                    evq.put(("log", f"unsupported geometry: {meta}"))
            elif kind == "chunk":
                rows = frame.apply_chunk(ev[1], ev[2])
                # Coalesce: report progress every chunk, rows only when ready.
                evq.put(("progress", frame.n_received, rows))
            elif kind == "end":
                ok = frame.crc_ok()
                evq.put(("end", ev[1], ok, frame.crc_hex()))
            elif kind == "log":
                evq.put(ev)


def list_serial_candidates():
    """Existing /dev serial ports, for friendly open-failure messages."""
    import glob
    found = []
    for pat in ("/dev/ttyACM*", "/dev/ttyUSB*"):
        found.extend(sorted(glob.glob(pat)))
    return found


def open_serial(port: str, baud: int):
    """Open pyserial, but raise SystemExit(2) with hints instead of traceback."""
    import serial
    try:
        # exclusive=True: a second fb_live on the same port fails fast instead
        # of silently splitting the RX stream (both instances then show
        # garbage/timeouts and TX echoes land in the wrong window).
        return serial.Serial(port, baud, timeout=1, exclusive=True)
    except Exception as e:  # noqa: BLE001 - translate to a clean message
        cands = list_serial_candidates()
        print(f"[live] ERROR: cannot open {port}: {e}", flush=True)
        if cands:
            print(f"[live] available ports: {' '.join(cands)}", flush=True)
            if port not in cands:
                print(f"[live] hint: ESPPORT={cands[0]} python3 Phase_18/tools/fb_live.py",
                      flush=True)
        else:
            print("[live] hint: no /dev/ttyACM* or /dev/ttyUSB* present — "
                  "plug in the DEV-KIT (USB-CDC) and check `dmesg | tail`.",
                  flush=True)
        print("[live] hint: no hardware? use --selftest --show for the demo window.",
              flush=True)
        raise SystemExit(2)


# ---------- GUI ----------

class LiveWindow:
    def __init__(self, root, img, img_label, frame, ser, ser_lock, evq, args):
        self.root = root
        self.img = img
        self.img_label = img_label
        self.frame = frame
        self.ser = ser
        self.ser_lock = ser_lock
        self.evq = evq
        self.args = args
        self.dirty = set()
        self.last_log = ""
        self.frames_done = 0
        self.status = None
        self.entry = None
        self.loop_var = None
        self.press_anchor = None  # (x_disp, y_disp) while button held
        self.shown_geom = None  # (w, h) the PhotoImage currently matches
        self.last_stream = time.monotonic()  # last begin/progress/end
        # Stall watchdog: re-issue dump when the stream stalls. Scaled by baud:
        # a full 768000-byte frame is ~1.06M line chars (~92 s @115200 but
        # ~12 s @921600), so a fixed 8 s timeout fires *mid-dump* on slow
        # links — and the firmware streamer is not re-entrant, so the restart
        # kills the in-flight frame and the window never completes (looks
        # stuck). Threshold ~= 1/3 frame time, clamped to [8 s, 60 s].
        try:
            _baud = int(getattr(args, "baud", 115200) or 115200)
        except (TypeError, ValueError):
            _baud = 115200
        self.dump_retry_s = max(8.0, min(60.0, 1060000 / (_baud / 10) / 3))

    def _send_serial_line(self, line: str) -> bool:
        try:
            with self.ser_lock:
                self.ser.write((line + "\n").encode())
                self.ser.flush()
            return True
        except Exception as e:  # noqa: BLE001
            self.set_status(f"send failed: {e}")
            return False

    def on_canvas_press(self, ev):
        """Mouse down on the screen image: anchor a potential tap/swipe."""
        if getattr(self.args, "no_touch", False):
            return
        self.press_anchor = (ev.x, ev.y)

    def on_canvas_release(self, ev):
        """Mouse up: click (slop < TAP_SLOP_PX) -> `tap`; drag -> `swipe`."""
        if getattr(self.args, "no_touch", False):
            return
        if self.press_anchor is None:
            return
        x0, y0 = self.press_anchor
        self.press_anchor = None
        dx, dy = ev.x - x0, ev.y - y0
        fw, fh, sc = self.frame.w, self.frame.h, self.frame.scale
        if dx * dx + dy * dy <= TAP_SLOP_PX * TAP_SLOP_PX:
            fx, fy = display_to_fw(ev.x, ev.y, sc, fw, fh)
            if self._send_serial_line(format_tap(fx, fy, fw, fh)):
                self.set_status(f"tap {fx} {fy} sent")
                self.show_sent(f"tap {fx} {fy}")
        else:
            ax, ay = display_to_fw(x0, y0, sc, fw, fh)
            bx, by = display_to_fw(ev.x, ev.y, sc, fw, fh)
            if self._send_serial_line(format_swipe(ax, ay, bx, by, fw, fh)):
                self.set_status(f"swipe {ax} {ay} -> {bx} {by} sent")
                self.show_sent(f"swipe {ax} {ay} {bx} {by}")

    def rebuild_image(self):
        """Resize the PhotoImage to the current frame geometry."""
        import tkinter as tk
        sw = self.frame.w // self.frame.scale
        sh = self.frame.h // self.frame.scale
        self.img = tk.PhotoImage(width=sw, height=sh)
        self.img.put("{#000000}", to=(0, 0, sw, sh))
        self.img_label.configure(image=self.img)
        self.shown_geom = (self.frame.w, self.frame.h)
        self.dirty.clear()
        self.root.title(f"Phase18 virtual FB LIVE {self.frame.w}x{self.frame.h} (degraded)")

    def put_display_row(self, y_disp: int):
        try:
            row = display_row_hex(bytes(self.frame.raw), y_disp,
                                  self.frame.scale, self.frame.w, self.frame.h)
        except IndexError:
            return
        self.img.put("{" + row + "}", to=(0, y_disp))

    def poll(self):
        # Bounded work per tick: an unbounded drain + full repaint lets a burst
        # (e.g. buffered serial after reset) backlog faster than tkinter can
        # render, starving the mainloop until the window looks dead. Leftover
        # events/rows wait for the next tick instead.
        drained = 0
        while drained < 200:
            try:
                ev = self.evq.get_nowait()
            except queue.Empty:
                break
            try:
                self.handle_event(ev)
            except Exception:  # noqa: BLE001 - a bad event must not kill the GUI
                pass
            drained += 1
        if self.dirty:
            for d in sorted(self.dirty)[:40]:
                try:
                    self.put_display_row(d)
                except Exception:  # noqa: BLE001 - same guarantee for rendering
                    pass
                self.dirty.discard(d)
        # Stall watchdog: the auto-dump can race device boot (line lost before
        # the console task runs) and then nothing arrives until the next END —
        # which never comes. Re-issue instead of sitting black forever.
        if time.monotonic() - self.last_stream > self.dump_retry_s:
            if self.loop_var is None or self.loop_var.get():
                self.set_status("no stream — retrying dump…")
                self.ask_dump()
                self.last_stream = time.monotonic()
        self.root.after(100, self.poll)

    def handle_event(self, ev):
        kind = ev[0]
        if kind == "begin":
            self.last_stream = time.monotonic()
            if self.shown_geom != (self.frame.w, self.frame.h):
                self.rebuild_image()
            self.set_status(f"streaming {self.frame.w}x{self.frame.h}… {ev[1].get('crc')}")
        elif kind == "progress":
            _, n, rows = ev
            self.last_stream = time.monotonic()
            self.dirty.update(rows)
            if n % 500 == 0 or n >= self.frame.nchunks:
                self.set_status(f"chunks {n}/{self.frame.nchunks} …")
        elif kind == "end":
            self.last_stream = time.monotonic()
            _, count, ok, crc = ev
            self.frames_done += 1
            mark = "OK" if ok else "CRC-MISMATCH"
            self.set_status(f"frame {self.frames_done}: {count} chunks crc={crc} {mark}")
            self.root.title(f"Phase18 virtual FB LIVE {self.frame.w}x{self.frame.h} [{crc} {mark}] (degraded)")
            # Paint any rows that completed on the final chunks.
            for d in range(self.frame.display_rows()):
                fw = d * self.frame.scale
                if self.frame._row_complete(fw):
                    self.dirty.add(d)
            if self.args.out:
                try:
                    rgb = fb_viewer.rgb565le_to_rgb888(
                        bytes(self.frame.raw), self.frame.w, self.frame.h)
                    fb_viewer.write_png(self.args.out, rgb, self.frame.w, self.frame.h)
                    self.set_status(self.status_text() + f" saved {self.args.out}")
                except Exception as e:  # noqa: BLE001
                    self.set_status(self.status_text() + f" save failed: {e}")
            if self.args.once:
                self.root.after(300, self.root.destroy)
            elif self.loop_var is not None and self.loop_var.get():
                self.root.after(int(self.args.loop_delay * 1000), self.ask_dump)
        elif kind == "log":
            self.last_log = ev[1]
            self.set_status(self.last_log)
            # Also print to the terminal: while fb_live holds the port there is
            # no monitor running, so this is the only place device replies
            # ([HVFB] tap/result/info) stay visible.
            print(f"[live] {ev[1]}", flush=True)

    def status_text(self):
        return self.status.cget("text") if self.status else ""

    def show_sent(self, cmd: str):
        """Mirror a sent tap/swipe into the command entry so the user sees
        what went out (the status line is overwritten by stream progress)."""
        try:
            if self.entry is not None:
                self.entry.delete(0, "end")
                self.entry.insert(0, cmd)
        except Exception:  # noqa: BLE001 - tkinter teardown races
            pass

    def set_status(self, msg: str):
        if self.status is not None:
            # Keep it one line for the small window.
            self.status.config(text=msg[-64:])
        else:
            self.last_log = msg

    def ask_dump(self):
        try:
            with self.ser_lock:
                self.ser.reset_input_buffer()
                self.ser.write(b"dump\n")
                self.ser.flush()
        except Exception as e:  # noqa: BLE001
            self.set_status(f"dump failed: {e}")

    def send_command(self, _ev=None):
        cmd = self.entry.get().strip() if self.entry else ""
        if not cmd:
            return
        try:
            with self.ser_lock:
                self.ser.write((cmd + "\n").encode())
                self.ser.flush()
            self.set_status(f"sent: {cmd}")
            if cmd == "dump":
                pass  # stream will arrive as FB_* lines
            self.entry.delete(0, "end")
        except Exception as e:  # noqa: BLE001
            self.set_status(f"send failed: {e}")


def run_gui(args, ser, ser_lock):
    import tkinter as tk

    scale = args.scale
    sw, sh = W // scale, H // scale
    frame = LiveFrame(scale=scale)
    evq: queue.Queue = queue.Queue()
    stop = threading.Event()
    req = threading.Event()

    root = tk.Tk()
    root.title("Phase18 virtual FB LIVE (degraded, no panel)")
    root.configure(bg="black")
    # Fixed-size emulator: controls must not stretch the window wider than
    # the screen image (that caused the grey side gutters in the first demo).
    root.resizable(False, False)
    img = tk.PhotoImage(width=sw, height=sh)
    # Start black.
    img.put("{#000000}", to=(0, 0, sw, sh))
    img_label = tk.Label(root, image=img, bg="black", bd=0, highlightthickness=0)
    img_label.pack()

    import tkinter.font as tkfont

    # Readable controls on hi-dpi screens: bump the app-wide defaults. (The
    # screen image itself stays 1:1 pixels — use --scale 1 for full size.)
    try:
        tkfont.nametofont("TkDefaultFont").configure(size=11)
        tkfont.nametofont("TkTextFont").configure(size=12)
    except Exception:  # noqa: BLE001 - headless/minimal tk builds
        pass
    big_font = ("TkDefaultFont", 13)

    win = LiveWindow(root, img, img_label, frame, ser, ser_lock, evq, args)
    img_label.bind("<Button-1>", win.on_canvas_press)
    img_label.bind("<ButtonRelease-1>", win.on_canvas_release)
    win.shown_geom = (frame.w, frame.h)
    status = tk.Label(root, text="waiting for dump… (~95s @115200 first frame)",
                      anchor="w", justify="left", wraplength=max(sw, 400))
    status.pack(fill="x", padx=6, pady=2)
    win.status = status

    # Command entry gets its own full-width row: tall, big font, impossible
    # to miss. Buttons live on the row below so they can't squeeze it.
    entry = tk.Entry(root, font=big_font, width=24)
    entry.pack(fill="x", padx=6, pady=4, ipady=6)
    entry.bind("<Return>", win.send_command)
    entry.focus_set()
    win.entry = entry

    brow = tk.Frame(root)
    brow.pack(fill="x", padx=6, pady=2)
    tk.Button(brow, text="Send", command=win.send_command).pack(side="left", padx=2)
    tk.Button(brow, text="Dump", command=win.ask_dump).pack(side="left", padx=2)

    loop_var = tk.BooleanVar(value=not args.once)
    tk.Checkbutton(brow, text="loop", variable=loop_var).pack(side="left", padx=2)
    win.loop_var = loop_var

    hint = tk.Label(root, text="cmds: info help save clear dump  (Enter=sends)",
                    anchor="w", justify="left")
    hint.pack(fill="x")
    if getattr(args, "no_touch", False):
        note = tk.Label(root, text="touch: OFF (--no-touch)", anchor="w")
    else:
        note = tk.Label(root, text="touch: click=tap, drag=swipe on the screen",
                        anchor="w", justify="left")
    note.pack(fill="x")

    th = threading.Thread(target=reader_thread,
                          args=(ser, frame, evq, stop, req, print),
                          daemon=True)
    th.start()
    root.after(100, win.poll)

    def on_close():
        stop.set()
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    stop.set()
    return 0


def run_headless(args, ser, ser_lock) -> int:
    """Capture frames without tkinter (CI / ssh-safe)."""
    frame = LiveFrame(scale=args.scale)
    evq: queue.Queue = queue.Queue()
    stop = threading.Event()
    req = threading.Event()
    th = threading.Thread(target=reader_thread,
                          args=(ser, frame, evq, stop, req, print),
                          daemon=True)
    th.start()
    frames = 0
    t0 = time.time()
    timeout = args.capture_timeout
    try:
        while True:
            try:
                ev = evq.get(timeout=1.0)
            except queue.Empty:
                if time.time() - t0 > timeout:
                    print("[live] capture timeout waiting for frames")
                    return 1
                continue
            kind = ev[0]
            if kind == "progress":
                _, n, _ = ev
                if n % 1000 == 0:
                    print(f"[live] ... {n}/{frame.nchunks} chunks", flush=True)
            elif kind == "end":
                _, count, ok, crc = ev
                frames += 1
                print(f"[live] frame {frames}: {frame.w}x{frame.h} {count} chunks crc={crc} "
                      f"{'OK' if ok else 'CRC-MISMATCH'}", flush=True)
                if not ok and not args.keep_bad:
                    return 2
                if args.out:
                    if not ok:
                        print("[live] WARNING: saving torn frame (--keep-bad)", flush=True)
                    rgb = fb_viewer.rgb565le_to_rgb888(
                        bytes(frame.raw), frame.w, frame.h)
                    fb_viewer.write_png(args.out, rgb, frame.w, frame.h)
                    print(f"[live] wrote {args.out}")
                if args.once or frames >= args.max_frames:
                    return 0
                if args.loop_delay > 0:
                    time.sleep(args.loop_delay)
                req.set()
            elif kind == "log":
                print(f"[live] {ev[1]}", flush=True)
            t0 = time.time()  # activity resets timeout
    finally:
        stop.set()
    return 0


def selftest_geometry(args):
    """Parse --geometry WxH (default portrait 480x800)."""
    g = (args.geometry or "480x800").lower()
    try:
        w, h = (int(v) for v in g.split("x"))
        fb_viewer.check_geometry(w, h, w * h * 2)
        return w, h
    except ValueError as e:
        sys.exit(f"ERROR: bad --geometry: {e}")


def run_selftest_show(args) -> int:
    """No-hardware demo: animate synthetic frames in the emulator window."""
    import tkinter as tk

    w, h = selftest_geometry(args)
    scale = args.scale
    sw, sh = w // scale, h // scale
    root = tk.Tk()
    root.title(f"Phase18 virtual FB LIVE [selftest {w}x{h}, no hardware] (degraded)")
    root.configure(bg="black")
    root.resizable(False, False)
    img = tk.PhotoImage(width=sw, height=sh)
    tk.Label(root, image=img, bg="black", bd=0, highlightthickness=0).pack()
    status = tk.Label(root, text="selftest", anchor="w", wraplength=sw)
    status.pack(fill="x")

    raws = []
    base = fb_viewer.make_selftest_frame(w, h)
    # Frame 2: inverted copy so the loop visibly flips.
    inv = bytearray(base)
    for i in range(0, len(inv), 2):
        px = inv[i] | (inv[i + 1] << 8)
        px ^= 0xFFFF
        inv[i] = px & 0xFF
        inv[i + 1] = (px >> 8) & 0xFF
    raws = [base, bytes(inv)]
    state = {"i": 0}

    def paint(raw: bytes):
        for y_disp in range(sh):
            row = display_row_hex(raw, y_disp, scale, w, h)
            img.put("{" + row + "}", to=(0, y_disp))

    def tick():
        raw = raws[state["i"] % len(raws)]
        t0 = time.time()
        paint(raw)
        dt = time.time() - t0
        crc = "%08X" % (binascii.crc32(raw) & 0xFFFFFFFF)
        status.config(text=f"selftest frame {state['i']} crc={crc} paint={dt:.2f}s")
        root.title(f"Phase18 virtual FB LIVE [selftest {crc}] (degraded)")
        if args.out and state["i"] == 0:
            fb_viewer.write_png(args.out, fb_viewer.rgb565le_to_rgb888(raw, w, h), w, h)
        state["i"] += 1
        if not (args.once and state["i"] >= 1):
            root.after(1500, tick)
        else:
            root.after(400, root.destroy)

    root.after(200, tick)
    root.mainloop()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 18 live screen emulator")
    ap.add_argument("--port", default=os.environ.get("ESPPORT", "/dev/ttyACM0"))
    ap.add_argument("--baud", type=int, default=115200,
                    help="console baud; must match the firmware "
                         "(seedsigner_screen_test runs 921600)")
    ap.add_argument("--scale", type=int, default=2, choices=(1, 2, 4),
                    help="downscale for laptop screens (default 2: 240x400 portrait, 400x240 landscape; 1 = full-size)")
    ap.add_argument("--out", default="fb_live.png",
                    help="PNG snapshot per frame (empty to disable)")
    ap.add_argument("--once", action="store_true",
                    help="capture/show a single frame then exit")
    ap.add_argument("--keep-bad", action="store_true",
                    help="save CRC-MISMATCH (torn animation) frames too, with a warning")
    ap.add_argument("--no-show", action="store_true",
                    help="headless capture, no tkinter window")
    ap.add_argument("--no-touch", action="store_true",
                    help="disable click-to-tap in the window (view-only)")
    ap.add_argument("--selftest", action="store_true",
                    help="no hardware: animate synthetic frames")
    ap.add_argument("--geometry", default="",
                    help="WxH for --selftest (default 480x800)")
    ap.add_argument("--loop-delay", type=float, default=2.0,
                    help="seconds between frames in loop mode")
    ap.add_argument("--max-frames", type=int, default=10**9)
    ap.add_argument("--capture-timeout", type=float, default=240.0)
    a = ap.parse_args()

    if a.selftest and a.no_show:
        w, h = selftest_geometry(a)
        raw = fb_viewer.make_selftest_frame(w, h)
        rgb = fb_viewer.rgb565le_to_rgb888(raw, w, h)
        if a.out:
            fb_viewer.write_png(a.out, rgb, w, h)
            print(f"[live] selftest wrote {a.out}")
        print(f"[live] selftest frame {w}x{h} len={len(raw)} "
              f"crc={binascii.crc32(raw) & 0xFFFFFFFF:08X}")
        return 0
    if a.selftest:
        return run_selftest_show(a)

    try:
        import serial  # noqa: F401 - needed for type only; open via helper
    except ImportError:
        sys.exit("ERROR: pyserial missing. Run inside the IDF env "
                 "(. ~/esp/esp-idf-v5.5/export.sh) or: pip install pyserial")

    ser = open_serial(a.port, a.baud)
    ser_lock = threading.Lock()
    time.sleep(0.5)
    print(f"[live] port={a.port} baud={a.baud} scale={a.scale} "
          f"{'once' if a.once else 'loop'} (degraded emulator, no panel)",
          flush=True)

    try:
        if a.no_show:
            return run_headless(a, ser, ser_lock)
        try:
            return run_gui(a, ser, ser_lock)
        except ImportError:
            print("[live] tkinter unavailable; falling back to headless")
            return run_headless(a, ser, ser_lock)
    finally:
        try:
            ser.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
