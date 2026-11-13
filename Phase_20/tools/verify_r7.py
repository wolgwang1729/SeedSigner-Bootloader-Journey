#!/usr/bin/env python3
"""Phase 20 R7 host interop check: recompute the device's AEAD output.

The payload's bench_aead encrypts a deterministic 128 KB pattern
(pt[i] = (i & 0xFF) ^ ((i >> 8) & 0xFF)) with a fixed throwaway key/nonce
(same constants as in canary_scrub.c) using IETF ChaCha20-Poly1305, then
prints SHA256(ct) + tag hex. This script recomputes both with the
`cryptography` lib and compares - proving the device runs standard
ChaCha20-Poly1305, not a local variant.

  python3 tools/verify_r7.py --bench-log logs/exp_r7-aead_<stamp>.log
"""
import argparse
import hashlib
import re
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

KEY = bytes([
    0x52, 0x37, 0x94, 0xa1, 0x0b, 0xc4, 0x7d, 0x2e,
    0x9f, 0x11, 0x63, 0x58, 0xe2, 0x4a, 0x0d, 0x77,
    0x3c, 0x99, 0xf0, 0x25, 0x6b, 0x81, 0xd4, 0xab,
    0x12, 0x34, 0x56, 0x78, 0x9a, 0xbc, 0xde, 0xf0])
NONCE = bytes(range(12))
ALEN = 128 * 1024


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench-log", required=True)
    args = ap.parse_args()

    log = Path(args.bench_log).read_text(errors="replace")
    m = re.search(r"BENCH_AEAD cth=([0-9a-f]{64}) tag=([0-9a-f]{32})", log)
    assert m, "BENCH_AEAD hash lines not found"
    dev_cth, dev_tag = m.group(1), m.group(2)

    pt = bytes(((i & 0xFF) ^ ((i >> 8) & 0xFF)) for i in range(ALEN))
    ct_and_tag = ChaCha20Poly1305(KEY).encrypt(NONCE, pt, None)
    ct, tag = ct_and_tag[:-16], ct_and_tag[-16:]
    exp_cth, exp_tag = hashlib.sha256(ct).hexdigest(), tag.hex()

    print(f"device cth = {dev_cth}")
    print(f"host   cth = {exp_cth}")
    print(f"device tag = {dev_tag}")
    print(f"host   tag = {exp_tag}")
    if (dev_cth, dev_tag) == (exp_cth, exp_tag):
        print("R7 VERIFY: MATCH (interop proven)")
        return 0
    print("R7 VERIFY: MISMATCH")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
