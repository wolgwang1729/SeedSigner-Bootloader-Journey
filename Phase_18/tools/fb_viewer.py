#!/usr/bin/env python3
"""Phase 18 desktop viewer: makes the DEV-KIT framebuffer visible on your PC.

Inputs (one required):
  --raw FB0.RAW        480x800 RGB565LE frame (default len 768000)
  --serial-log MON.LOG monitor capture containing FB_BEGIN/FB_CHUNK/FB_END
  --selftest           generate a synthetic frame in memory (no hardware)

What it does:
  - reassembles / reads the frame, checks length + CRC32,
  - writes OUT.PNG (stdlib-only PNG encoder) and optionally OUT.PPM,
  - optionally shows the image with tkinter (if available).

Zero third-party deps: struct + zlib + tkinter (optional) from stdlib.

UART protocol (from virtual_fb_demo/main/virtual_fb_demo.c):
  FB_BEGIN <w> <h> <len> <crc32-hex>
  FB_CHUNK <seq> <base64>
  FB_END <count>
"""
import argparse
import base64
import binascii
import os
import struct
import sys
import zlib

W = 480
H = 800
FRAME_LEN = W * H * 2  # RGB565LE

# Geometries the emulator accepts: 480x800 portrait (ST7701 console /
# touch_test) and 800x480 landscape (SeedSigner 4.3" UI). Both are 768000
# bytes, i.e. 4000x 192B UART chunks — only the pixel indexing differs.
SUPPORTED_GEOMETRIES = ((480, 800), (800, 480))


def frame_len(w: int, h: int) -> int:
    return w * h * 2


def check_geometry(w: int, h: int, ln: int) -> None:
    if (w, h) not in SUPPORTED_GEOMETRIES:
        raise ValueError(f"unsupported geometry {w}x{h} (want one of {SUPPORTED_GEOMETRIES})")
    if ln != frame_len(w, h):
        raise ValueError(f"frame len {ln} != {w}x{h} expected {frame_len(w, h)}")


def rgb565le_to_rgb888(raw: bytes, w: int = W, h: int = H) -> bytes:
    if len(raw) != w * h * 2:
        raise ValueError(f"frame len {len(raw)} != expected {w * h * 2} ({w}x{h})")
    out = bytearray(w * h * 3)
    o = 0
    for i in range(0, len(raw), 2):
        px = raw[i] | (raw[i + 1] << 8)
        r = ((px >> 11) & 0x1F) * 255 // 31
        g = ((px >> 5) & 0x3F) * 255 // 63
        b = (px & 0x1F) * 255 // 31
        out[o] = r
        out[o + 1] = g
        out[o + 2] = b
        o += 3
    return bytes(out)


def write_png(path: str, rgb: bytes, w: int = W, h: int = H) -> None:
    def chunk(typ: bytes, data: bytes) -> bytes:
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", binascii.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 6)))
        f.write(chunk(b"IEND", b""))


def write_ppm(path: str, rgb: bytes, w: int = W, h: int = H) -> None:
    with open(path, "wb") as f:
        f.write(f"P6\n{w} {h}\n255\n".encode())
        f.write(rgb)


def parse_serial_log(path: str) -> tuple[bytes, dict]:
    chunks: dict[int, bytes] = {}
    meta: dict = {}
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("FB_BEGIN"):
                _, w, h, ln, crc = line.split()
                meta = {"w": int(w), "h": int(h), "len": int(ln), "crc": crc.upper()}
            elif line.startswith("FB_CHUNK"):
                _, seq, b64 = line.split(None, 2)
                chunks[int(seq)] = base64.b64decode(b64)
            elif line.startswith("FB_END"):
                meta["count"] = int(line.split()[1])
    if not meta:
        raise ValueError("no FB_BEGIN in log")
    check_geometry(meta["w"], meta["h"], meta["len"])
    if len(chunks) != meta.get("count", len(chunks)):
        raise ValueError(f"missing chunks: have {len(chunks)}, want {meta.get('count')}")
    raw = b"".join(chunks[i] for i in range(len(chunks)))
    if len(raw) != meta["len"]:
        raise ValueError(f"reassembled len {len(raw)} != {meta['len']}")
    got = f"{binascii.crc32(raw) & 0xFFFFFFFF:08X}"
    if got != meta["crc"]:
        raise ValueError(f"CRC mismatch: stream {meta['crc']} vs computed {got}")
    return raw, meta


def make_selftest_frame(w: int = W, h: int = H) -> bytes:
    """Same spirit as firmware pattern 0: bars + white card + finders.

    Positions scale proportionally from the 480x800 original so both
    supported geometries get an equivalent pattern.
    """
    check_geometry(w, h, w * h * 2)
    bars = [(255, 0, 0), (255, 165, 0), (255, 255, 0), (0, 255, 0),
            (0, 255, 255), (0, 0, 255), (255, 0, 255), (255, 255, 255)]
    raw = bytearray(w * h * 2)

    def px(x, y, r, g, b):
        if 0 <= x < w and 0 <= y < h:
            v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            o = (y * w + x) * 2
            raw[o] = v & 0xFF
            raw[o + 1] = (v >> 8) & 0xFF

    for x in range(w):
        r, g, b = bars[(x * 8) // w]
        for y in range(h):
            px(x, y, r, g, b)
    for x in range(w):
        for t in range(6):
            px(x, t, 0, 0, 0)
            px(x, h - 1 - t, 0, 0, 0)

    def rect(x0, y0, x1, y1, r, g, b):
        for y in range(y0, y1):
            for x in range(x0, x1):
                px(x, y, r, g, b)

    # White card: proportional inset of the original (40,160)-(W-40,H-200).
    rect(w * 40 // 480, h * 160 // 800, w - w * 40 // 480, h - h * 200 // 800,
         255, 255, 255)

    def finder(x0, y0, s):
        rect(x0, y0, x0 + s, y0 + s, 0, 0, 0)
        m = s // 7
        rect(x0 + m, y0 + m, x0 + s - m, y0 + s - m, 255, 255, 255)
        rect(x0 + 2 * m, y0 + 2 * m, x0 + s - 2 * m, y0 + s - 2 * m, 0, 0, 0)

    fs = min(w, h) * 120 // 480
    # Original 480x800 top-lefts as fractions: (70,190), (290,190), (70,430).
    finder(w * 70 // 480, h * 190 // 800, fs)
    finder(w * 290 // 480, h * 190 // 800, fs)
    finder(w * 70 // 480, h * 430 // 800, fs)
    return bytes(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 18 virtual-FB viewer")
    ap.add_argument("--raw", help="fb0.raw from SD card")
    ap.add_argument("--serial-log", help="monitor capture with FB_CHUNK lines")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default="fb0.png")
    ap.add_argument("--ppm", default="")
    ap.add_argument("--show", action="store_true", help="open tkinter window")
    ap.add_argument("--geometry", default="",
                    help="WxH for --raw/--selftest (default 480x800; serial-log uses stream meta)")
    a = ap.parse_args()

    srcs = bool(a.raw) + bool(a.serial_log) + bool(a.selftest)
    if srcs != 1:
        ap.error("give exactly one of --raw | --serial-log | --selftest")

    gw, gh = W, H
    if a.geometry:
        try:
            gw, gh = (int(v) for v in a.geometry.lower().split("x"))
            check_geometry(gw, gh, gw * gh * 2)
        except ValueError as e:
            ap.error(f"bad --geometry: {e}")

    if a.selftest:
        raw = make_selftest_frame(gw, gh)
        print(f"[viewer] selftest frame {gw}x{gh} len={len(raw)}")
        w, h = gw, gh
    elif a.raw:
        with open(a.raw, "rb") as f:
            raw = f.read()
        print(f"[viewer] raw file {a.raw} len={len(raw)}")
        w, h = gw, gh
    else:
        raw, meta = parse_serial_log(a.serial_log)
        print(f"[viewer] serial {a.serial_log} chunks={meta['count']} crc={meta['crc']} OK")
        w, h = meta["w"], meta["h"]

    crc = f"{binascii.crc32(raw) & 0xFFFFFFFF:08X}"
    print(f"[viewer] frame {w}x{h} RGB565LE len={len(raw)} crc={crc}")
    rgb = rgb565le_to_rgb888(raw, w, h)
    write_png(a.out, rgb, w, h)
    print(f"[viewer] wrote {a.out} ({os.path.getsize(a.out)} bytes)")
    if a.ppm:
        write_ppm(a.ppm, rgb, w, h)
        print(f"[viewer] wrote {a.ppm}")

    if a.show:
        try:
            import tkinter as tk
        except ImportError:
            print("[viewer] tkinter unavailable; PNG saved, not shown")
            return 0
        root = tk.Tk()
        root.title(f"Phase18 virtual FB {w}x{h} ({crc})")
        # Downscale 2x for laptop screens: nearest neighbour in pure python.
        sw, sh = w // 2, h // 2
        small = bytearray(sw * sh * 3)
        for y in range(sh):
            for x in range(sw):
                si = ((y * 2) * w + (x * 2)) * 3
                di = (y * sw + x) * 3
                small[di:di + 3] = rgb[si:si + 3]
        img = tk.PhotoImage(width=sw, height=sh)
        # PhotoImage put() is slow per-pixel; write rows as hex spans.
        for y in range(sh):
            row = " ".join(
                "#%02x%02x%02x" % (small[(y * sw + x) * 3], small[(y * sw + x) * 3 + 1], small[(y * sw + x) * 3 + 2])
                for x in range(sw)
            )
            img.put("{" + row + "}", to=(0, y))
        tk.Label(root, image=img).pack()
        root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
