#!/usr/bin/env python3
"""Host-side round trip for the Phase 23-A verification path (no hardware).

Simulates what the device is expected to emit, so the *verification* half can be
trusted before any firmware exists:

    fixtures/psbt.txt  --sign with the fixture seed-->  signed PSBT
                       --SeedSigner UREncoder-------->  ur:crypto-psbt frames
                       --[P23] QR log lines---------->  frames.log

`verify_signed_psbt.py` then checks the log exactly as it will check a device run.
Signing here also proves the fixture is signable at all (a broken fixture would
otherwise look like a device failure).

This is not evidence about the device. It is a gate on the tooling.
"""

import base64
import os
import sys

import json

DEFAULT_EMBIT = os.path.expanduser(
    "~/Desktop/seedsigner-micropython-builder/deps/embit/src")
DEFAULT_SEEDSIGNER = os.path.expanduser(
    "~/Desktop/seedsigner-micropython-builder/deps/seedsigner/src")
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.normpath(os.path.join(HERE, "..", "fixtures"))
OUT = os.path.normpath(os.path.join(HERE, "..", "build", "host_roundtrip"))
FRAGMENT = 400  # Sparrow "Normal" / SeedSigner default UR density


def main():
    sys.path.insert(0, DEFAULT_EMBIT)
    sys.path.insert(0, DEFAULT_SEEDSIGNER)

    expected = json.load(open(os.path.join(FIXTURES, "expected.json")))
    mnemonic = expected["mnemonic"]
    expected_sigs = expected.get("expected_signatures", 1)

    from embit import bip39
    from embit.bip32 import HDKey
    from embit.psbt import PSBT
    from seedsigner.helpers.ur2.ur import UR
    from seedsigner.helpers.ur2.ur_encoder import UREncoder

    b64 = open(os.path.join(FIXTURES, "psbt.txt")).read().strip()
    psbt = PSBT.from_base64(b64)

    root = HDKey.from_seed(bip39.mnemonic_to_seed(mnemonic))
    n = psbt.sign_with(root)
    if n != expected_sigs:
        raise SystemExit("expected %d signature(s), got %d" % (expected_sigs, n))
    print("signed %d input(s)" % n)

    # ur:crypto-psbt = CBOR tag 310 over a byte string of the PSBT.
    raw = psbt.serialize()
    cbor = b"\xd9\x01\x36" + _cbor_bytestring_header(len(raw)) + raw
    ur = UR("crypto-psbt", bytearray(cbor))

    enc = UREncoder(ur, FRAGMENT)
    total = enc.fountain_encoder.seq_len()
    if total < 1:
        total = 1
    frames = []
    for _ in range(total):
        frames.append(enc.next_part())
    print("encoded %d UR frame(s), fragment %d B" % (len(frames), FRAGMENT))

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "frames.log")
    with open(path, "w") as f:
        for i, frame in enumerate(frames):
            f.write("[P23] QR %d %s\n" % (i, frame))
    print("wrote %s" % path)
    return path


def _cbor_bytestring_header(n):
    if n < 24:
        return bytes([0x40 | n])
    if n < 256:
        return bytes([0x58, n])
    if n < 65536:
        return b"\x59" + n.to_bytes(2, "big")
    return b"\x5a" + n.to_bytes(4, "big")


if __name__ == "__main__":
    print(main())
