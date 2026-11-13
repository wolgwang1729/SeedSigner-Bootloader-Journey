"""Host tests for Phase 18 live emulator helpers (no hardware, no tkinter)."""
import base64
import binascii
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import fb_live


def test_parse_begin_tolerates_monitor_prefix():
    m = fb_live.parse_fb_begin("I (1234) P18: FB_BEGIN 480 800 768000 1A038B92")
    assert m == {"w": 480, "h": 800, "len": 768000, "crc": "1A038B92"}
    assert fb_live.parse_fb_begin("[P18] alive tick=1") is None


def test_parse_chunk_and_end_roundtrip():
    payload = bytes(range(192))
    b64 = base64.b64encode(payload).decode()
    seq, back = fb_live.parse_fb_chunk(f"FB_CHUNK 7 {b64}")
    assert seq == 7 and back == payload
    # monitor prefix tolerated
    seq2, back2 = fb_live.parse_fb_chunk(f"I (99) P18: FB_CHUNK 7 {b64}")
    assert (seq2, back2) == (7, payload)
    assert fb_live.parse_fb_end("FB_END 4000") == 4000
    assert fb_live.parse_fb_end("noise") is None


def test_live_frame_progressive_rows_and_crc():
    import fb_viewer
    raw = fb_viewer.make_selftest_frame()
    crc = "%08X" % (binascii.crc32(raw) & 0xFFFFFFFF)
    fr = fb_live.LiveFrame(scale=2)
    fr.reset({"w": 480, "h": 800, "len": len(raw), "crc": crc})
    painted = []
    for seq in range(fb_live.NCHUNKS):
        rows = fr.apply_chunk(seq, raw[seq * 192:(seq + 1) * 192])
        painted.extend(rows)
    assert fr.is_complete()
    assert fr.crc_ok()
    assert bytes(fr.raw) == raw
    # scale=2 -> 400 display rows, each exactly once, in order.
    assert painted == list(range(400))
    # Out-of-range / short-middle chunks are ignored.
    assert fr.apply_chunk(9999, b"x" * 192) == []
    assert fr.apply_chunk(0, b"short") == []


def test_display_row_hex_geometry():
    import fb_viewer
    raw = fb_viewer.make_selftest_frame()
    row = fb_live.display_row_hex(raw, 0, scale=2)
    toks = row.split(" ")
    assert len(toks) == 240
    assert all(t.startswith("#") and len(t) == 7 for t in toks)
    row1 = fb_live.display_row_hex(raw, 0, scale=1)
    assert len(row1.split(" ")) == 480


def test_landscape_frame_reassembly_and_rows():
    import fb_viewer
    raw = fb_viewer.make_selftest_frame(800, 480)
    assert len(raw) == 800 * 480 * 2
    crc = "%08X" % (binascii.crc32(raw) & 0xFFFFFFFF)
    fr = fb_live.LiveFrame(scale=2)
    assert fr.reset({"w": 800, "h": 480, "len": len(raw), "crc": crc}) is True
    assert fr.nchunks == 4000
    painted = []
    for seq in range(fr.nchunks):
        painted.extend(fr.apply_chunk(seq, raw[seq * 192:(seq + 1) * 192]))
    assert fr.is_complete()
    assert fr.crc_ok()
    assert bytes(fr.raw) == raw
    # scale=2 over 800x480 -> 240 display rows, each exactly once, in order.
    assert painted == list(range(240))
    assert fr.display_rows() == 240
    row = fb_live.display_row_hex(raw, 0, scale=2, w=800, h=480)
    assert len(row.split(" ")) == 400


def test_landscape_straddling_chunks_complete_rows():
    import fb_viewer
    raw = fb_viewer.make_selftest_frame(800, 480)
    crc = "%08X" % (binascii.crc32(raw) & 0xFFFFFFFF)
    fr = fb_live.LiveFrame(scale=2)
    assert fr.reset({"w": 800, "h": 480, "len": len(raw), "crc": crc}) is True
    # Feed in reverse: rows complete only when all covering chunks land.
    painted = []
    for seq in reversed(range(fr.nchunks)):
        painted.extend(fr.apply_chunk(seq, raw[seq * 192:(seq + 1) * 192]))
    assert fr.is_complete()
    assert sorted(painted) == list(range(240))
    # A single chunk must not complete any display row.
    fr2 = fb_live.LiveFrame(scale=2)
    assert fr2.reset({"w": 800, "h": 480, "len": len(raw), "crc": crc}) is True
    assert fr2.apply_chunk(0, raw[0:192]) == []


def test_rejects_unsupported_geometry():
    fr = fb_live.LiveFrame()
    assert fr.reset({"w": 320, "h": 240, "len": 320 * 240 * 2, "crc": "0" * 8}) is False
    # Portrait still the default after a rejected reset.
    assert (fr.w, fr.h) == (480, 800)


class _FakeRoot:
    def __init__(self):
        self.after_calls = 0
        self.titles = []

    def after(self, ms, fn):
        self.after_calls += 1

    def title(self, t):
        self.titles.append(t)


class _FakeImg:
    def __init__(self):
        self.puts = []

    def put(self, s, to=None):
        self.puts.append((s, to))


class _FakeArgs:
    once = False
    out = ""
    loop_delay = 2.0
    no_touch = True


def _make_window(n_events=500):
    import queue
    import fb_viewer
    frame = fb_live.LiveFrame(scale=2)
    raw = fb_viewer.make_selftest_frame()
    crc = "%08X" % (__import__("binascii").crc32(raw) & 0xFFFFFFFF)
    assert frame.reset({"w": 480, "h": 800, "len": len(raw), "crc": crc})
    # Land the first 400 chunks so rows 0..39 really render (not IndexError).
    for seq in range(400):
        frame.apply_chunk(seq, raw[seq * 192:(seq + 1) * 192])
    evq = queue.Queue()
    evq.put(("begin", {"w": 480, "h": 800, "len": len(raw), "crc": crc}))
    for i in range(n_events):
        evq.put(("progress", (i % 4000) + 1, [i % 40]))
    win = fb_live.LiveWindow(_FakeRoot(), _FakeImg(), None, frame, None, None,
                             evq, _FakeArgs())
    # img_label only needed for rebuilds; geometry is stable here.
    win.img_label = None
    win.shown_geom = (480, 800)
    return win, evq


def test_poll_is_bounded_under_burst():
    """A serial burst after reset must not wedge the GUI: poll() does bounded
    work per tick and survives rendering, leaving the rest queued/dirty."""
    import time
    win, evq = _make_window(500)
    t0 = time.monotonic()
    win.poll()
    dt = time.monotonic() - t0
    assert dt < 5.0, f"poll took {dt:.1f}s on a 500-event burst"
    assert not evq.empty(), "all 500 events drained in one tick (unbounded)"
    assert len(win.img.puts) <= 40, "rendered too many rows in one tick"
    assert win.root.after_calls == 1, "poll must reschedule itself"


def test_rejects_bad_crc():
    fr = fb_live.LiveFrame()
    fr.reset({"w": 480, "h": 800, "len": fb_live.FRAME_LEN, "crc": "DEADBEEF"})
    fr.apply_chunk(0, b"\x00" * 192)
    assert not fr.crc_ok()
    assert not fr.is_complete()


def test_open_missing_port_exits_clean(capsys):
    try:
        fb_live.open_serial("/dev/ttyACM_NONEXISTENT_XYZ", 115200)
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("missing port must raise SystemExit(2)")
    out = capsys.readouterr().out
    assert "ERROR: cannot open" in out
    assert "--selftest" in out


def test_list_serial_candidates_returns_list():
    assert isinstance(fb_live.list_serial_candidates(), list)


def test_open_serial_uses_exclusive(monkeypatch):
    """Second fb_live on one port must fail fast, not split the stream."""
    import sys
    import types
    seen = {}

    class FakeSerial:
        def __init__(self, port, baud, timeout=None, **kw):
            seen.update(port=port, baud=baud, timeout=timeout, **kw)
            if kw.get("exclusive") is not True:
                raise AssertionError("exclusive=True required")
            raise RuntimeError("port busy")

    fake = types.ModuleType("serial")
    fake.Serial = FakeSerial
    monkeypatch.setitem(sys.modules, "serial", fake)
    try:
        fb_live.open_serial("/dev/ttyACM0", 115200)
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("busy port must raise SystemExit(2)")
    assert seen.get("exclusive") is True


def test_display_to_fw_scaling_and_clamp():
    assert fb_live.display_to_fw(0, 0, 2) == (0, 0)
    assert fb_live.display_to_fw(239, 399, 2) == (478, 798)
    # window edges map inside the firmware frame, never out of bounds
    assert fb_live.display_to_fw(240, 400, 2) == (479, 799)
    assert fb_live.display_to_fw(-5, 900, 2) == (0, 799)
    assert fb_live.display_to_fw(120, 200, 1) == (120, 200)


def test_tap_format_parse_roundtrip():
    line = fb_live.format_tap(123, 456)
    assert line == "tap 123 456"
    assert fb_live.parse_tap_line(line) == (123, 456)
    assert fb_live.parse_tap_line("I (99) HVFB: tap 123 456") == (123, 456)
    assert fb_live.parse_tap_line("tap 480 800") is None  # out of range
    assert fb_live.parse_tap_line("tap 1") is None
    assert fb_live.parse_tap_line("swipe 1 2 3 4") is None
    assert fb_live.format_tap(9999, -3) == "tap 479 0"  # clamped


def test_swipe_format_parse_roundtrip():
    line = fb_live.format_swipe(10, 20, 400, 700)
    assert line == "swipe 10 20 400 700"
    assert fb_live.parse_swipe_line(line) == (10, 20, 400, 700)
    assert fb_live.parse_swipe_line("swipe 1 2 3") is None
    assert fb_live.parse_swipe_line("swipe 0 0 800 0") is None  # outside union bounds
    assert fb_live.parse_swipe_line("tap 1 2") is None
    # Landscape coordinates (x up to 799) are accepted host-side.
    assert fb_live.parse_swipe_line("swipe 0 0 799 479") == (0, 0, 799, 479)
    assert fb_live.format_swipe(0, 0, 799, 479, 800, 480) == "swipe 0 0 799 479"


def _synth_stream(n_chunks=40, chunk_raw=192, w=48, h=80, corrupt=None):
    """Synthetic stream text. corrupt(seq, line) -> mutated line."""
    import base64
    import binascii
    raw = bytes(((i * 13) % 256) for i in range(n_chunks * chunk_raw))
    crc = "%08X" % (binascii.crc32(raw) & 0xFFFFFFFF)
    lines = [f"FB_BEGIN {w} {h} {len(raw)} {crc}"]
    for seq in range(n_chunks):
        b64 = base64.b64encode(raw[seq * chunk_raw:(seq + 1) * chunk_raw]).decode()
        line = f"FB_CHUNK {seq} {b64}"
        if corrupt:
            line = corrupt(seq, line) or line
        lines.append(line)
    lines.append(f"FB_END {n_chunks}")
    return "\n".join(lines) + "\n", raw, crc


def _drain(parser, text, frags=(None,)):
    """Feed text whole or in fragments; collect all events."""
    events = []
    if frags == (None,):
        return events + parser.feed(text)
    i, k = 0, 0
    while i < len(text):
        n = frags[k % len(frags)]
        events.extend(parser.feed(text[i:i + n]))
        i += n
        k += 1
    return events


def test_parser_clean_stream():
    text, raw, crc = _synth_stream()
    evs = _drain(fb_live.StreamParser(), text)
    kinds = [e[0] for e in evs]
    assert kinds[0] == "begin"
    assert kinds[-1] == "end"
    assert kinds.count("chunk") == 40
    assert evs[-1] == ("end", 40)
    assert evs[0][1] == {"w": 48, "h": 80, "len": len(raw), "crc": crc}
    # Same events feeding in odd fragments.
    evs2 = _drain(fb_live.StreamParser(), text, frags=(7, 53, 200))
    assert [(e[0], e[1]) for e in evs if e[0] != "chunk"] == \
           [(e[0], e[1]) for e in evs2 if e[0] != "chunk"]
    assert [e[2] for e in evs if e[0] == "chunk"] == \
           [e[2] for e in evs2 if e[0] == "chunk"]


def test_parser_skips_tap_echo_mid_chunk():
    tap = "[HVFB] tap 71 53\n"

    def corrupt(seq, line):
        if seq == 5:
            head, tail = line[:100], line[100:]
            return head + "\n" + tap + tail
        return line

    text, raw, crc = _synth_stream(corrupt=corrupt)
    evs = _drain(fb_live.StreamParser(), text)
    chunks = {e[1]: e[2] for e in evs if e[0] == "chunk"}
    assert len(chunks) == 40
    assert b"".join(chunks[i] for i in range(40)) == raw
    logs = [e[1] for e in evs if e[0] == "log"]
    assert any("tap 71 53" in m for m in logs)


def test_parser_split_header_and_glued_lines():
    text, raw, crc = _synth_stream(n_chunks=4)
    # Glue everything (all newlines lost) — headers still found, payloads slice.
    glued = text.replace("\n", "")
    evs = _drain(fb_live.StreamParser(), glued)
    assert [e[0] for e in evs][0] == "begin"
    assert [e[0] for e in evs][-1] == "end"
    assert len([e for e in evs if e[0] == "chunk"]) == 4
    # Header split across feeds reassembles.
    p = fb_live.StreamParser()
    assert p.feed("FB_BE") == []
    evs = p.feed("GIN 48 80 7680 DEADBEEF\n")
    assert evs and evs[0][0] == "begin"


def test_parser_overrun_loss_abandons_chunk():
    def corrupt(seq, line):
        if seq == 3:
            return line[:200]  # 56 payload chars lost to overrun
        return line

    text, raw, crc = _synth_stream(n_chunks=8, corrupt=corrupt)
    evs = _drain(fb_live.StreamParser(), text)
    got = sorted(e[1] for e in evs if e[0] == "chunk")
    assert 3 not in got  # torn chunk dropped, not half-applied
    assert len(got) == 7
    assert evs[-1][0] == "end"


def test_parser_forwards_logs_and_drops_orphans():
    p = fb_live.StreamParser()
    assert p.feed("I (123) board: hello\n") == [("log", "I (123) board: hello")]
    assert p.feed("QUJDRA==\n") == []  # orphan base64, no chunk context: silent
    assert p.feed(">>> \n") == [("log", ">>>")]
    # Unsupported geometry still surfaces a begin (reader judges it).
    evs = p.feed("FB_BEGIN 320 240 153600 00000000\n")
    assert evs and evs[0][0] == "begin"


def test_parser_end_to_end_frame_with_interleaving():
    """Parser + LiveFrame: interleaved tap echoes don't break reassembly,
    but overrun-eaten payload bytes still fail CRC downstream (correct)."""
    import binascii
    import fb_viewer
    raw = fb_viewer.make_selftest_frame(800, 480)
    crc = "%08X" % (binascii.crc32(raw) & 0xFFFFFFFF)
    import base64
    lines = [f"FB_BEGIN 800 480 {len(raw)} {crc}"]
    for seq in range(0, 4000):
        lines.append(f"FB_CHUNK {seq} "
                     + base64.b64encode(raw[seq * 192:(seq + 1) * 192]).decode())
    lines.append("FB_END 4000")
    parts = lines
    for seq in (100, 500, 1000, 1500, 2000, 2500, 3000, 3500, 3900, 3999):
        idx = 1 + seq
        b64 = parts[idx].split(" ", 2)[2]
        # Tap echo splits the line AND the first 10 payload chars are eaten
        # (overrun-style loss on those lines).
        parts[idx] = parts[idx][:20] + "\n[HVFB] tap 71 53\n" + b64[10:]
    text = "\n".join(parts) + "\n"
    parser = fb_live.StreamParser()
    frame = fb_live.LiveFrame(scale=2)
    n_chunks = 0
    for ev in parser.feed(text):
        if ev[0] == "begin":
            assert frame.reset(ev[1])
        elif ev[0] == "chunk":
            frame.apply_chunk(ev[1], ev[2])
            n_chunks += 1
    assert n_chunks == 4000 - 10
    assert not frame.is_complete()
    assert not frame.crc_ok()


def test_parser_blank_line_mid_chunk_does_not_hang():
    """Regression: blank / whitespace-only line splitting a chunk payload
    must be skipped, not hang the reader thread (frozen window).

    Old line parser skipped blanks (`if not line: continue`); the defrag
    parser looped forever on them while pending (pos never advanced).
    """
    import base64
    payload = base64.b64encode(bytes([0xAB] * 192)).decode()
    assert len(payload) == 256
    p = fb_live.StreamParser()
    assert p.feed("FB_CHUNK 5 " + payload[:100] + "\n") == []
    # Blank + whitespace-only lines mid-payload: no hang, no events yet.
    assert p.feed("\n") == []
    assert p.feed("   \r\n") == []
    evs = p.feed(payload[100:] + "\n")
    assert len(evs) == 1 and evs[0][0] == "chunk"
    assert evs[0][1] == 5 and evs[0][2] == bytes([0xAB] * 192)
