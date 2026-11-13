# Phase 23 - Verification & Execution Tools

This directory contains host-side test harnesses, fixture generators, orchestrator scripts, and consensus verification tools supporting Phase 23.

## Tools Summary

| Script | Purpose |
|---|---|
| `verify_signed_psbt.py` | Extracts animated `ur:crypto-psbt` frames from UART log streams, reassembles the signed PSBT, and verifies all 3 ECDSA signatures against BIP-143 sighashes and `testqrs.com` ground truth. |
| `host_roundtrip.py` | Host simulation executing the complete SeedQR decode -> Seed derivation -> PSBT parse -> multi-input sign -> animated UR2 fountain frame generation sequence without hardware. |
| `run_p4_stateless_sign.sh` | Automated end-to-end orchestrator that builds, signs, boots the ESP32-P4 image in `esp-emu`, captures the execution log, and runs `verify_signed_psbt.py`. |
| `gen_fixture.py` | Generates embedded fixtures (`psbt.txt`, `seedqr.txt`, `expected.json`, `_headless_fixtures.py`) from official `testqrs.com` test vectors. |
| `headless_signer.py` | Host Python implementation of the headless signing state machine mirroring firmware execution. |

## Usage Examples

Run host consensus verification against execution logs:
```sh
python3 tools/verify_signed_psbt.py logs/p4_hw_stateless_sign.txt
```

Run host roundtrip test:
```sh
python3 tools/host_roundtrip.py
python3 tools/verify_signed_psbt.py build/host_roundtrip/frames.log
```
