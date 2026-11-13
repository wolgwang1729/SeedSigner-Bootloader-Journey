#!/usr/bin/env python3
"""Phase 20 attack-bundle mint: fresh negative tests from today's valid base.

Phase_14/attacks/*.bin are stale (signed under a retired test key -
good.bin halts with `0 valid signatures` on the current loader). This
script mints an equivalent set from the CURRENTLY-VALID canary_r0 bundle
+ payload signing key, so R1/R2/R6 verdicts test the intended gate and
not key drift.

  python3 tools/make_attacks.py

Inputs (defaults point at the R0 rig):
  --raw   raw app image (no Specter header)
  --good  signed bundle that verifies today
  --key   payload signing key (test profile)

Outputs in Phase_20/attacks/:
  good.bin            copy of the valid bundle (accept case)
  raw.bin             raw app image (no Specter header -> T6-style halt)
  tamper.bin          good bundle + 1 flipped bit in the image region
  badsig.bin          good bundle + 1 flipped bit in the signature region
  wrong-platform.bin  same image, platform=seedsigner_esp32s3, valid sig
  downgrade.bin       same image, pl_ver=0, valid sig

All reversible host-side files. No board, flash, or eFuse contact.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
PH20 = HERE.parent.parent
LOADER_REPO = Path(os.environ.get("LOADER_REPO", str(Path.home() / "Desktop" / "seedsigner-esp32-bootloader")))
SIGN_TOOL = LOADER_REPO / "tools" / "generate_signed_payload.py"


def flip(data: bytearray, off: int) -> None:
    data[off] ^= 0x01


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(
        PH20 / "test_payloads" / "canary_scrub_r0" / "build" / "canary_scrub.bin"))
    ap.add_argument("--good", default=str(
        PH20 / "test_payloads" / "canary_scrub_r0" / "build" / "canary_r0_esp32p4.bin"))
    ap.add_argument("--key", default=str(LOADER_REPO / "payload_signing_key.pem"))
    ap.add_argument("--out", default=str(PH20 / "attacks"))
    args = ap.parse_args()

    raw = Path(args.raw).read_bytes()
    good = bytearray(Path(args.good).read_bytes())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # Bundle layout: [main header 256B][image len(raw)][sig header 256B][sig].
    assert len(good) == 256 + len(raw) + 256 + (len(good) - 256 - len(raw) - 256), \
        "unexpected bundle geometry"
    sig_len = len(good) - 256 - len(raw) - 256
    print(f"base: image={len(raw)}B sig={sig_len}B total={len(good)}B")

    shutil.copyfile(args.good, out / "good.bin")
    shutil.copyfile(args.raw, out / "raw.bin")

    t = bytearray(good)
    flip(t, 256 + 100)  # inside the image region -> hash/sig mismatch
    (out / "tamper.bin").write_bytes(t)

    b = bytearray(good)
    flip(b, len(b) - 10)  # inside the signature payload
    (out / "badsig.bin").write_bytes(b)

    def sign(extra, dest):
        subprocess.run(
            [sys.executable, str(SIGN_TOOL), "--key", args.key] + extra +
            [args.raw, str(dest)],
            check=True, capture_output=True,
        )

    sign(["--platform", "seedsigner_esp32s3", "--version", "1"],
         out / "wrong-platform.bin")
    sign(["--platform", "seedsigner_esp32p4", "--version", "0"],
         out / "downgrade.bin")

    for f in sorted(out.glob("*.bin")):
        print(f"  {f.name:20s} {f.stat().st_size}B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
