#!/usr/bin/env python3
"""Fail the build if the raw payload image would overlap the Phase 19 canary.

P4 canary at 0x48400000 = 4 MB into the PSRAM window (0x48000000 base).
S3 canary at 0x3C7F0000 = linear offset 0x7F0000 (~8 MB - 64 KB).
The staged PSRAM footprint must end below the canary base.
This is a size heuristic (raw file size); the loader's esp_image_plan
bounds-checks the true segment footprint at boot.
"""
import argparse
import os
import sys

LIMITS = {
    "esp32p4": 4 * 1024 * 1024,
    "esp32s3": 0x7F0000,
}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("image", help="Raw app image (e.g. build/canary_scrub.bin)")
    p.add_argument("--target", choices=["esp32p4", "esp32s3"], default="esp32p4")
    args = p.parse_args()
    size = os.path.getsize(args.image)
    limit = LIMITS[args.target]
    if size >= limit:
        print(f"FAIL: {args.image} is {size} bytes >= canary limit {limit} "
              f"for {args.target} — would overlap CANARY_PADDR", file=sys.stderr)
        sys.exit(1)
    print(f"OK: {size} bytes < canary limit {limit} ({args.target})")

if __name__ == "__main__":
    main()
