"""Host-side tests for the Phase 18 virtual-FB viewer (no hardware needed)."""
import base64
import binascii
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import fb_viewer


def test_selftest_frame_geometry_and_crc(tmp_path):
    raw = fb_viewer.make_selftest_frame()
    assert len(raw) == fb_viewer.FRAME_LEN == 480 * 800 * 2
    # Top-left pixel must be the first (red) bar, not black border interplay:
    # row 100 is below the 6px border, x=10 is inside bar 0.
    o = (100 * 480 + 10) * 2
    px = raw[o] | (raw[o + 1] << 8)
    assert (px >> 11) & 0x1F == 31  # full red
    assert ((px >> 5) & 0x3F) < 4   # ~zero green


def test_raw_to_png_roundtrip(tmp_path):
    raw = fb_viewer.make_selftest_frame()
    rgb = fb_viewer.rgb565le_to_rgb888(raw)
    assert len(rgb) == 480 * 800 * 3
    out = str(tmp_path / "fb0.png")
    fb_viewer.write_png(out, rgb)
    with open(out, "rb") as f:
        sig = f.read(8)
        assert sig == b"\x89PNG\r\n\x1a\n"
        ihdr_len = struct.unpack(">I", f.read(4))[0]
        ihdr_typ = f.read(4)
        assert (ihdr_len, ihdr_typ) == (13, b"IHDR")
        w, h = struct.unpack(">II", f.read(8))
        assert (w, h) == (480, 800)


def test_serial_log_reassembly_and_crc(tmp_path):
    raw = fb_viewer.make_selftest_frame()
    crc = f"{binascii.crc32(raw) & 0xFFFFFFFF:08X}"
    lines = [f"noise before", f"FB_BEGIN 480 800 {len(raw)} {crc}"]
    seq = 0
    for off in range(0, len(raw), 192):
        lines.append(f"FB_CHUNK {seq} " + base64.b64encode(raw[off:off + 192]).decode())
        seq += 1
    lines.append(f"FB_END {seq}")
    lines.append("noise after")
    log = tmp_path / "mon.log"
    log.write_text("\n".join(lines) + "\n")
    back, meta = fb_viewer.parse_serial_log(str(log))
    assert back == raw
    assert meta["crc"] == crc


def test_rejects_bad_geometry(tmp_path):
    p = tmp_path / "short.raw"
    p.write_bytes(b"\x00" * 100)
    try:
        fb_viewer.rgb565le_to_rgb888(p.read_bytes())
    except ValueError:
        return
    raise AssertionError("short frame must raise ValueError")
