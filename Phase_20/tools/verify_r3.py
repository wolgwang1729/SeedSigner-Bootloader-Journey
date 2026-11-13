#!/usr/bin/env python3
"""Phase 20 R3 host verifier: recompute the bound words off-board.

Reads the install state straight from flash (reversible reads only),
takes the board's R3 log lines (salt provision + cid_pack + proof words),
and recomputes bound = SHA256(fill_hash || salt || cid_pack) ->
4 BIP-39 words. Any mismatch fails loudly: it would mean the board's
derivation is not the documented formula.

  python3 tools/verify_r3.py --boot-log logs/r3_bootA.log

Flash reads (no writes, no eFuse):
  fill_hash  <- flash 0x21000 (anti_phish_state: magic 0x41504F4B + hash[32])
  salt       <- flash 0x23000 (salt_state: magic 0x53414C54 + salt[16])
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

PORT = "/dev/ttyACM0"
BAUD = "921600"
LOADER_REPO = Path(os.environ.get("LOADER_REPO", str(Path.home() / "Desktop" / "seedsigner-esp32-bootloader")))


def read_flash(addr: int, size: int) -> bytes:
    out = "/tmp/verify_r3_read.bin"
    subprocess.run(
        [sys.executable, "-m", "esptool", "--port", PORT, "--baud", BAUD,
         "read_flash", hex(addr), hex(size), out],
        check=True, capture_output=True, timeout=120,
    )
    return Path(out).read_bytes()


def load_wordlist():
    words = []
    for line in (LOADER_REPO / "main" / "bip39_wordlist.c").read_text().splitlines():
        m = re.match(r'\s*"([a-z]+)"', line)
        if m:
            words.append(m.group(1))
    assert len(words) == 2048, f"wordlist parsed {len(words)} words"
    return words


def words_from_hash(digest: bytes, wordlist):
    # Same bit order as extract_bits(): MSB-first, 11 bits per word.
    bits = "".join(f"{b:08b}" for b in digest)
    return [wordlist[int(bits[i * 11:(i + 1) * 11], 2)] for i in range(4)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot-log", required=True)
    args = ap.parse_args()

    nvs = read_flash(0x21000, 64)
    assert int.from_bytes(nvs[0:4], "little") == 0x41504F4B, "anti-phish state missing"
    fill_hash = nvs[4:36]

    sal = read_flash(0x23000, 32)
    assert int.from_bytes(sal[0:4], "little") == 0x53414C54, "salt state missing"
    salt = sal[4:20]

    log = Path(args.boot_log).read_text(errors="replace")
    m_cid = re.search(r"R3 cid_pack=([0-9a-f]{32})", log)
    m_words = re.search(r"ANTI-PHISHING PROOF: (\w+) (\w+) (\w+) (\w+)", log)
    assert m_cid and m_words, "R3 log lines not found in boot log"
    cid_pack = bytes.fromhex(m_cid.group(1))
    board_words = list(m_words.groups())

    bound = hashlib.sha256(fill_hash + salt + cid_pack).digest()
    expect = words_from_hash(bound, load_wordlist())

    print(f"fill_hash = {fill_hash.hex()}")
    print(f"salt      = {salt.hex()}")
    print(f"cid_pack  = {cid_pack.hex()}")
    print(f"bound     = {bound.hex()}")
    print(f"board     = {' '.join(board_words)}")
    print(f"recomputed= {' '.join(expect)}")
    if expect == board_words:
        print("R3 VERIFY: MATCH")
        return 0
    print("R3 VERIFY: MISMATCH")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
