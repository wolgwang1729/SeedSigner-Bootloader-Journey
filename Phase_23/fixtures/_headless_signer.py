"""Phase 23-A Headless PSBT Signer for ESP32-P4 Stateless SeedSigner.

Runs on MicroPython (on physical silicon or in esp-emu) or CPython.
Ingests the deterministic test vector PSBT and SeedQR from _headless_fixtures,
executes the genuine SeedSigner signing pipeline, and emits UR frames to stdout:

    [P23] QR <i> <ur:crypto-psbt/...>

These lines are monitored and verified by Phase_23/tools/verify_signed_psbt.py.
"""

import gc
import sys
import time

try:
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
except AttributeError:
    # CPython fallback
    ticks_ms = lambda: int(time.time() * 1000)
    ticks_diff = lambda a, b: a - b


def run():
    print("[P23] === Phase 23-A Headless PSBT Signing Starting ===")
    t0 = ticks_ms()

    # 1. Imports from genuine SeedSigner and embit
    from seedsigner.models.decode_qr import DecodeQR
    from seedsigner.models.seed import Seed
    from seedsigner.models.psbt_parser import PSBTParser
    from seedsigner.models.settings import SettingsConstants
    from seedsigner.helpers.ur2.ur import UR
    from seedsigner.helpers.ur2.ur_encoder import UREncoder
    from urtypes.crypto import PSBT as UR_PSBT

    # 2. Ingest Fixtures
    try:
        from _headless_fixtures import FILES
    except ImportError:
        # Fallback if fixtures are placed in current directory
        import os
        fixtures_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtures")
        FILES = {
            "psbt.txt": open(os.path.join(fixtures_dir, "psbt.txt")).read().strip(),
            "seedqr.txt": open(os.path.join(fixtures_dir, "seedqr.txt")).read().strip(),
        }

    psbt_raw = FILES["psbt.txt"]
    seedqr_raw = FILES["seedqr.txt"]

    # 3. Decode PSBT via SeedSigner DecodeQR
    t_psbt = ticks_ms()
    psbt_dec = DecodeQR()
    psbt_dec.add_data(psbt_raw)
    if not (psbt_dec.is_complete and psbt_dec.is_psbt):
        raise RuntimeError("PSBT decode failed")
    psbt = psbt_dec.get_psbt()
    print("[P23] Ingested PSBT in %d ms (txid: %s)" % (
        ticks_diff(ticks_ms(), t_psbt),
        psbt.tx.txid().hex()
    ))

    # 4. Decode SeedQR via SeedSigner DecodeQR
    t_seed = ticks_ms()
    seed_dec = DecodeQR()
    seed_dec.add_data(seedqr_raw)
    if not (seed_dec.is_complete and seed_dec.is_seed):
        raise RuntimeError("SeedQR decode failed")
    mnemonic = seed_dec.get_seed_phrase()
    seed = Seed(mnemonic=mnemonic)
    fingerprint = seed.get_fingerprint(SettingsConstants.MAINNET)
    print("[P23] Ingested Seed in %d ms (fingerprint: %s)" % (
        ticks_diff(ticks_ms(), t_seed),
        fingerprint
    ))

    # 5. Parse PSBT with Seed
    t_parse = ticks_ms()
    parser = PSBTParser(psbt, seed=seed, network=SettingsConstants.MAINNET)
    print("[P23] Parsed PSBT in %d ms (change: %d sats, fee: %d sats, inputs: %d)" % (
        ticks_diff(ticks_ms(), t_parse),
        parser.change_amount,
        parser.fee_amount,
        parser.num_inputs
    ))

    # 6. Sign PSBT
    t_sign = ticks_ms()
    before_sigs = PSBTParser.sig_count(psbt)
    psbt.sign_with(parser.root)
    trimmed = PSBTParser.trim(psbt)
    after_sigs = PSBTParser.sig_count(trimmed)
    added = after_sigs - before_sigs
    print("[P23] Signed PSBT in %d ms (signatures added: %d)" % (
        ticks_diff(ticks_ms(), t_sign),
        added
    ))
    if added < 1:
        raise RuntimeError("Signing failed: 0 signatures added")

    # Clean up parser and reclaim ECC temporary allocations before UR encoding
    del parser
    gc.collect()

    # 7. Export via UR frames
    t_export = ticks_ms()
    cbor = UR_PSBT(trimmed.serialize()).to_cbor()
    ur = UR("crypto-psbt", bytearray(cbor))
    encoder = UREncoder(ur, max_fragment_len=400)
    total_parts = encoder.fountain_encoder.seq_len()
    if total_parts < 1:
        total_parts = 1

    for i in range(total_parts):
        part = encoder.next_part()
        print("[P23] QR %d %s" % (i, part))

    print("[P23] Exported %d UR frame(s) in %d ms" % (
        total_parts,
        ticks_diff(ticks_ms(), t_export)
    ))

    total_time = ticks_diff(ticks_ms(), t0)
    mem_free = getattr(gc, "mem_free", lambda: 0)()
    print("[P23] SUCCESS: full stateless signing flow finished in %d ms (free heap: %d B)" % (
        total_time,
        mem_free
    ))
    return True


if __name__ == "__main__":
    run()
