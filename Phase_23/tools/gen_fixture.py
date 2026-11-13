#!/usr/bin/env python3
"""Generate the Phase 23-A signing fixture (no network, no hardware).

Produces, deterministically, from a throwaway BIP-39 test-vector seed:

  fixtures/psbt.txt                 single-frame base64 PSBT (SeedSigner PSBT__BASE64)
  fixtures/seedqr.txt               numeric SeedQR (12 words x 4 decimal digits)
  fixtures/_headless_fixtures.py    frozen fallback for the esp-emu build
  fixtures/expected.json            values the host verifier asserts against

The seed is the public BIP-39 test vector ("abandon ... about"). The funding
transaction exists on no chain, so the PSBT is structurally valid and signable but
can never be broadcast. Never put real funds on anything generated here.

embit is the same library the firmware signs with, taken from the builder's pinned
submodule, so fixture and device agree bit-for-bit on addresses and sighashes.
"""

import argparse
import json
import os
import sys

DEFAULT_EMBIT = os.path.expanduser(
    "~/Desktop/seedsigner-micropython-builder/deps/embit/src")

MNEMONIC = (
    "abandon abandon abandon abandon abandon abandon "
    "abandon abandon abandon abandon abandon about"
)
# Synthetic previous output. 32 bytes of 0x11 repeated; never existed on any chain.
FUNDING_TXID = "11" * 32
FUNDING_VOUT = 0
FUNDING_SATS = 100_000
SEND_SATS = 60_000
FEE_SATS = 1_000

# A second throwaway key for the recipient, so the payment is not to ourselves.
RECIPIENT_MNEMONIC = (
    "legal winner thank year wave sausage worth useful legal "
    "winner thank yellow"
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures"))
    ap.add_argument("--embit", default=DEFAULT_EMBIT)
    args = ap.parse_args()

    sys.path.insert(0, args.embit)
    from embit import bip32, bip39, networks, script
    from embit.psbt import PSBT, DerivationPath
    from embit.transaction import (
        Transaction, TransactionInput, TransactionOutput)
    from embit.wordlists.bip39 import WORDLIST

    net = networks.NETWORKS["main"]

    seed = bip39.mnemonic_to_seed(MNEMONIC)
    root = bip32.HDKey.from_seed(seed)
    acct = root.derive("m/84h/0h/0h")
    receive = acct.derive("m/0/0")
    change = acct.derive("m/1/0")

    recipient_root = bip32.HDKey.from_seed(bip39.mnemonic_to_seed(RECIPIENT_MNEMONIC))
    recipient = recipient_root.derive("m/84h/0h/0h/0/0")

    our_spk = script.p2wpkh(receive.get_public_key())
    change_spk = script.p2wpkh(change.get_public_key())
    recipient_spk = script.p2wpkh(recipient.get_public_key())

    tx = Transaction(
        version=2,
        vin=[TransactionInput(bytes.fromhex(FUNDING_TXID), FUNDING_VOUT)],
        vout=[
            TransactionOutput(SEND_SATS, recipient_spk),
            TransactionOutput(FUNDING_SATS - SEND_SATS - FEE_SATS, change_spk),
        ],
        locktime=0,
    )

    psbt = PSBT(tx)
    inp = psbt.inputs[0]
    inp.witness_utxo = TransactionOutput(FUNDING_SATS, our_spk)
    # BIP-32 derivation lets SeedSigner confirm the input belongs to this seed.
    acct_path = [84 + 0x80000000, 0x80000000, 0x80000000]
    inp.bip32_derivations[receive.get_public_key()] = DerivationPath(
        root.my_fingerprint, acct_path + [0, 0])
    psbt.outputs[1].bip32_derivations[change.get_public_key()] = DerivationPath(
        root.my_fingerprint, acct_path + [1, 0])

    psbt_b64 = psbt.to_base64()

    # Numeric SeedQR: each word -> 4-digit decimal wordlist index.
    words = MNEMONIC.split()
    seedqr = "".join("%04d" % WORDLIST.index(w) for w in words)

    expected = {
        "mnemonic_test_vector": MNEMONIC,
        "master_fingerprint": root.my_fingerprint.hex(),
        "network": "main",
        "script_type": "p2wpkh",
        "derivation": "m/84h/0h/0h",
        "unsigned_txid": tx.txid().hex(),
        "funding_txid": FUNDING_TXID,
        "funding_vout": FUNDING_VOUT,
        "funding_sats": FUNDING_SATS,
        "fee_sats": FEE_SATS,
        "outputs": [
            {"address": recipient_spk.address(net), "sats": SEND_SATS},
            {"address": change_spk.address(net), "sats": FUNDING_SATS - SEND_SATS - FEE_SATS},
        ],
        "change_address": change_spk.address(net),
        "change_derivation": "m/84h/0h/0h/1/0",
        "signing_pubkey": receive.get_public_key().sec().hex(),
        "seedqr_words": len(words),
        "psbt_bytes": len(psbt.serialize()),
    }

    os.makedirs(args.out, exist_ok=True)

    def write(name, text):
        path = os.path.join(args.out, name)
        with open(path, "w") as f:
            f.write(text)
        print("wrote %-28s %6d bytes" % (name, len(text)))

    write("psbt.txt", psbt_b64 + "\n")
    write("seedqr.txt", seedqr + "\n")
    write("expected.json", json.dumps(expected, indent=2) + "\n")

    frozen = '''"""Frozen fixtures for the Phase 23-A harness build (GENERATED).

Copied into the frozen SeedSigner app only for the harness variant; a production
bundle has no _headless_fixtures module at all. Regenerate with
Phase_23/tools/gen_fixture.py -- do not edit by hand.
"""

FILES = {
    "psbt.txt": %r,
    "seedqr.txt": %r,
}

# Scan sessions in flow order: the PSBT is scanned first, then the seed QR to
# sign it with (PSBTSelectSeedView -> "Scan a seed").
SCAN_QUEUE = ["psbt.txt", "seedqr.txt"]

# Filled in from a real run: see Phase_23/tools/parse_screen_log.py.
SCREEN_SCRIPT = []
''' % (psbt_b64, seedqr)
    write("_headless_fixtures.py", frozen)

    print("\nunsigned txid: %s" % expected["unsigned_txid"])
    print("change:        %s" % expected["change_address"])
    print("seedqr:        %d digits" % len(seedqr))


if __name__ == "__main__":
    main()
