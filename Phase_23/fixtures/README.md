# Phase 23 - Test Fixtures

This directory contains test vectors and pre-baked frozen fixtures derived from the official SeedSigner test suite at `testqrs.com`.

## Fixture Set: `ss_native_segwit-change-3in`

- **Scenario:** Native SegWit (P2WPKH), Send with Change, 3 Inputs.
- **Identity:** Alice (24 words, master fingerprint `814d5ff8`).
- **Unsigned TXID:** `2a6f31c59e8d351a6d4a4002ce3b1b515d771add6610b21a1d7717f197311ad1`.
- **Inputs:** 3 Native SegWit inputs of 100,000 sats each (total 300,000 sats).
- **Outputs:**
  - Destination: `bc1qp75cd269r0m7rt0zgylmu83ge60d3zw3erg4vc` (193,334 sats).
  - Change: `bc1qrvzkqptcvh9trl4seumytkd42e4w0yfxya948s` (96,666 sats).
- **Fee:** 10,000 sats.

## Files

| File | Description |
|---|---|
| `psbt.txt` | Base64-encoded unsigned PSBT (551 bytes). |
| `seedqr.txt` | Standard numeric SeedQR representation for Alice. |
| `expected.json` | Scenario metadata, txid, fee, and sighash validation array from `testqrs.com`. |
| `_headless_fixtures.py` | Python module containing embedded base64 fixtures frozen into firmware. |
| `_headless_signer.py` | Embedded execution runner performing headless ingest, derivation, signing, and UR export. |
