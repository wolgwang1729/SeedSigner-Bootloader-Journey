# loader_changes - Phase 20 Modular Patches

Patches here are lossless diffs against the `seedsigner-esp32-bootloader` `main` branch. The mainline repository takes no direct commits from this experimental phase; experiments are evaluated on scratch copies and discarded after logging.

To apply from a scratch clone of the bootloader repository:

```bash
cp -a ~/Desktop/seedsigner-esp32-bootloader /tmp/rX_loader
cd /tmp/rX_loader
patch -p1 < path/to/Phase_20/loader_changes/r2-rollback.patch
idf.py set-target esp32p4 && idf.py build
```

## Patch Inventory

| Patch | New Files | Modified Files | Experimental Property Evaluated |
|---|---|---|---|
| `r2-rollback.patch` | `main/rollback.{c,h}` | `main/main.c` (hook after `pl_ver<1` gate), `main/CMakeLists.txt` | R2 reversible monotonic anti-rollback: NVS sector at `0x1000` tracks `{magic "ROLB", max_ver}`. Refuses downgraded bundles; NVS erase resets counter. |
| `r3-salt-bind.patch` | `main/salt_bind.{c,h}` | `main/anti_phish.c`, `main/targets/esp32p4/storage_p4.c`, `main/CMakeLists.txt` | R3 software-bound anti-phishing words: `SHA256(fill_hash \|\| salt \|\| cid_pack)`. Salt stored in NVS sector `0x2000`, CID captured prior to unmount. |
| `r4-verify-bench.patch` | None | `main/main.c`, `keys/test/vendor_keys.c`, `keys/vendor_keys.h` | R4 2-of-2 secp256k1 multisig verification timing; threshold changed from 1 to 2; throwaway test pubkeys embedded. |
| `r5-nojmp.patch` | None | `main/targets/esp32p4/jump_p4.c` | R5c no-JMP candidate: executes zero-mapping SRAM payloads directly while cleanly refusing XIP payloads fail-closed. |
| `r6-double-read.patch` | None | `main/targets/esp32p4/storage_p4.c` | R6a double-read variant: performs two independent reads and memory compares, verifying the second buffer (+90 ms cost). |
