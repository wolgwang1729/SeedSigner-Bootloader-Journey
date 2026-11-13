# Phase 20 Host and Test Tools

This directory contains host-side test drivers, verification scripts, and negative attack-bundle generators for the Phase 20 alternate secure routes campaign. All tools operate headlessly over serial (`/dev/ttyACM0`) or perform offline cryptographic operations. Zero irreversible eFuse operations are performed.

## Tool Inventory

| Tool | Purpose | Route |
|---|---|---|
| `verify_r7.py` | Host ChaCha20-Poly1305 AEAD interop verification against standard Python `cryptography` library | R7 |
| `verify_r3.py` | Host anti-phishing recomputation verifying `SHA256(fill_hash \|\| salt \|\| cid_pack)` against board BIP-39 words | R3 |
| `make_attacks.py` | Fresh negative attack bundle generator (generates `good.bin`, `raw.bin`, `tamper.bin`, `badsig.bin`, `wrong-platform.bin`, `downgrade.bin`) | R1, R2 |
| `sign_multisig.py` | Multi-key Specter multisig signing tool supporting threshold tests | R4 |
| `canary_session.py` | Headless serial session driver for automated command sequencing, reset injection, and reboot log collection | R0 |
| `tear_upload.py` | Power-loss simulation harness killing SD uploads mid-stream to prove atomic staging semantics | R6 |
| `boot_capture.py` | Automated 25-second raw UART boot log capture utility | Diagnostics |

## Usage Examples

### 1. Cryptographic Interop Verification (R7)
```bash
python3 tools/verify_r7.py --bench-log ./logs/exp_r7-aead_20261016_190309.log
```

### 2. Software-Bound Anti-Phishing Verification (R3)
```bash
python3 tools/verify_r3.py --boot-log ./logs/r3_bootA_saltA.log
```

### 3. Generate Fresh Negative Attack Bundles
```bash
python3 tools/make_attacks.py
```

### 4. Automated Canary Session Driver
```bash
python3 tools/canary_session.py status selftest
python3 tools/canary_session.py --tag r0-control scrub_off plant fault_restart
python3 tools/canary_session.py --tag r0-patched scrub_on plant fault_restart
```

### 5. Mid-Stream Upload Power-Cut Simulation
```bash
python3 tools/tear_upload.py ./attacks/badsig.bin --kill-at 100000
```
