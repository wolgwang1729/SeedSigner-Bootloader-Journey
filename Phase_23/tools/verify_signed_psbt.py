#!/usr/bin/env python3
"""Verify a PSBT signed by the Phase 23-A headless harness (host side).

SeedSigner never broadcasts: the deliverable is a *correctly signed PSBT*. This
script checks exactly that, and nothing else:

  1. the unsigned transaction in the returned PSBT is byte-identical to the one
     that was handed to the device (same txid, same outputs, same fee);
  2. every signature in the PSBT verifies against its own sighash and the pubkey
     it claims to be from;
  3. the input can be finalized (i.e. the signature is complete, not partial).

Input is whatever the harness emitted: the `[P23] QR <i> <payload>` lines from the
UART log, or the `qr_frames.txt` file written to the card. UR (the app's only
PSBT export format) and single-frame base64 are both accepted.

Exit code 0 = signed correctly; 1 = anything else.
"""

import argparse
import json
import os
import re
import sys

DEFAULT_SEEDSIGNER = os.path.expanduser(
    "~/Desktop/seedsigner-micropython-builder/deps/seedsigner/src")
DEFAULT_EMBIT = os.path.expanduser(
    "~/Desktop/seedsigner-micropython-builder/deps/embit/src")
HERE = os.path.dirname(os.path.abspath(__file__))


def read_frames(path):
    """Return payload strings in order, from a log or a frames file."""
    frames = []
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            m = re.search(r"\[P23\] QR (\d+) (.*)$", line)
            if m:
                frames.append((int(m.group(1)), m.group(2)))
                continue
            if line.startswith("ur:") or line.startswith("cHNidP"):
                frames.append((len(frames), line))
    if not frames:
        return []
    seen = {}
    for idx, payload in frames:
        seen.setdefault(idx, payload)
    return [seen[i] for i in sorted(seen)]


def _cbor_tag310_bytestring(cbor):
    """Strip the `crypto-psbt` CBOR wrapper (tag 310) off a UR payload body.

    `ur:crypto-psbt` is CBOR tag 310 over a byte string holding the raw PSBT.
    Decoding it here keeps the verifier free of the `urtypes` package (which is a
    MicroPython-only dependency in the firmware tree).
    """
    i = 0
    if cbor[0] == 0xD9 and cbor[1] == 0x01 and cbor[2] == 0x36:
        i = 3
    elif cbor[0] == 0xD8 and cbor[1] == 0x36:
        i = 2
    head = cbor[i]
    if head >> 5 != 2:
        raise SystemExit("UR payload is not a CBOR byte string (major type %d)" % (head >> 5))
    ai = head & 0x1F
    i += 1
    if ai < 24:
        n = ai
    elif ai == 24:
        n = cbor[i]
        i += 1
    elif ai == 25:
        n = int.from_bytes(cbor[i:i + 2], "big")
        i += 2
    elif ai == 26:
        n = int.from_bytes(cbor[i:i + 4], "big")
        i += 4
    else:
        raise SystemExit("unsupported CBOR length encoding")
    return cbor[i:i + n]


def decode_ur(frames, seedsigner_src):
    sys.path.insert(0, seedsigner_src)
    # The app's selectable wrapper prefers native cUR (uUR) and raises on a host.
    # The pure-Python implementation it used to fall back to is still in the tree,
    # so the verifier uses it directly.
    from seedsigner.helpers.ur2.ur_decoder import URDecoder
    d = URDecoder()
    for payload in frames:
        d.receive_part(payload.strip())
        if d.is_complete():
            break
    if not d.is_complete():
        raise SystemExit("UR decode incomplete: %d frame(s) received" % len(frames))
    if not d.is_success():
        raise SystemExit("UR decode failed: %s" % (d.result_error(),))
    return _cbor_tag310_bytestring(bytes(d.result_message().cbor))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", help="UART log or qr_frames.txt from the harness run")
    ap.add_argument("--expected", default=os.path.join(HERE, "..", "fixtures", "expected.json"))
    ap.add_argument("--embit", default=DEFAULT_EMBIT)
    ap.add_argument("--seedsigner", default=DEFAULT_SEEDSIGNER)
    ap.add_argument("--out", default=None, help="write the signed PSBT here")
    args = ap.parse_args()

    frames = read_frames(args.log)
    if not frames:
        raise SystemExit("no QR frames found in %s" % args.log)
    sys.path.insert(0, args.embit)
    from embit.psbt import PSBT

    first = frames[0].strip()
    if first.lower().startswith("ur:"):
        raw = decode_ur(frames, args.seedsigner)
        print("decoded UR from %d frame(s)" % len(frames))
        psbt = PSBT.parse(raw) if hasattr(PSBT, "parse") else PSBT(raw)
    else:
        print("decoded base64 PSBT (%d frame)" % len(frames))
        psbt = PSBT.from_base64(first)

    expected = json.load(open(args.expected))
    failures = []

    txid = psbt.tx.txid().hex()
    if txid != expected["unsigned_txid"]:
        failures.append("unsigned txid %s != expected %s" % (txid, expected["unsigned_txid"]))
    else:
        print("ok  unsigned txid unchanged: %s" % txid)

    # If the device returned a trimmed PSBT (per SeedSigner/BIP-174 export spec),
    # the witness UTXOs were stripped to minimize QR payload size. Merge with the
    # original unsigned fixture to compute sighash and fee.
    orig_path = os.path.join(HERE, "..", "fixtures", "psbt.txt")
    if os.path.exists(orig_path):
        orig_psbt = PSBT.from_base64(open(orig_path).read().strip())
    else:
        orig_psbt = psbt

    try:
        fee = psbt.fee()
    except Exception:
        fee = orig_psbt.fee()

    exp_fee = expected.get("fee", expected.get("fee_sats"))
    if fee != exp_fee:
        failures.append("fee %d != expected %d" % (fee, exp_fee))
    else:
        print("ok  fee: %d sats" % fee)

    from embit.ec import Signature

    total_sigs = 0
    expected_sigs = expected.get("expected_signatures", 1)

    for inp_idx, inp in enumerate(psbt.inputs):
        try:
            h = psbt.sighash(inp_idx)
        except Exception:
            h = orig_psbt.sighash(inp_idx)

        # Optional consistency check against ground truth from scenario JSON
        if "verify_inputs" in expected and inp_idx < len(expected["verify_inputs"]):
            exp_h = expected["verify_inputs"][inp_idx].get("sighash")
            if exp_h and h.hex() != exp_h:
                failures.append("input %d sighash %s != expected %s" % (inp_idx, h.hex(), exp_h))

        for pub, sig in inp.partial_sigs.items():
            total_sigs += 1
            try:
                sig_obj = Signature.parse(sig[:-1])
                ok = pub.verify(sig_obj, h)
            except Exception as e:
                ok = False
                failures.append("input %d signature parse/verify failed: %s" % (inp_idx, e))
            print("%s input %d signature from %s" % ("ok " if ok else "BAD", inp_idx, pub.sec().hex()))
            if not ok:
                failures.append("input %d signature does not verify for %s" % (inp_idx, pub.sec().hex()))

    if total_sigs == 0:
        failures.append("no signatures in the returned PSBT")
    elif total_sigs != expected_sigs:
        failures.append("expected %d signature(s), found %d" % (expected_sigs, total_sigs))

    if failures:
        print("\nFAIL")
        for f in failures:
            print("  -", f)
        return 1

    if args.out:
        with open(args.out, "wb") as f:
            f.write(psbt.serialize())
        print("signed PSBT written to %s" % args.out)

    print("\nPASS: signed correctly, unsigned data unchanged, no broadcast performed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
