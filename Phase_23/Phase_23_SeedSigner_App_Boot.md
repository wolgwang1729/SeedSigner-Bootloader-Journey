# Phase 23: Full SeedSigner App Boot and Stateless Signing

- **Date:** November 10, 2026 (Updated November 12, 2026)
- **Author:** Mayank (wolgwang)
- **Project:** SeedSigner Secure Boot - Bitshala Fellowship
- **Status:** Complete (Slice A) - Verified on physical ESP32-P4 rev 1.3 silicon, ESP32-P4 esp-emu, and ESP32-S3 esp-emu. Zero physical eFuse burns. Slice B (optics/display) deferred pending hardware arrival.
- **Hardware:** ESP32-P4-WIFI6-DEV-KIT headless (v1.3 silicon, 16 MB flash) + esp-emu v0.50.0 (ESP32-P4 and ESP32-S3).
- **Scope Notice:** Proves full genuine SeedSigner Bitcoin PSBT signing pipeline execution statelessly from PSRAM through the Secure Boot V2 chain without display hardware or irreversible eFuse burns.

---

## 1. Context & Architecture (Slice A vs Slice B)

Physical LCD and camera modules (`ESP32-P4-WIFI6-Touch-LCD-4.3-C`) are not available right now. Rather than halting progress or churning roadmap phase numbers, Phase 23 is structured into two cleanly delineated slices:

| Slice | Focus | Hardware Required | Status |
|---|---|---|---|
| **Slice A** | **Headless PSBT Signing & App Stack** | None (Runs in `esp-emu` & headless dev-kit) | Complete (Nov 10, 2026) |
| **Slice B** | **Air-Gapped Optics & On-Screen Proofs** | 4.3" DSI LCD + OV5647 camera | Pending hardware arrival |

### The Slice A Core Premise

SeedSigner's core value proposition is that it is a **secure Bitcoin transaction signer**:
1. Ingests an unsigned PSBT (normally via camera scan of animated UR/BBQR or base64 QR).
2. Verifies inputs and outputs against a loaded master fingerprint and derivation path.
3. Signs matching inputs with the loaded seed (`embit.psbt.PSBT.sign_with`).
4. Exports the signed transaction via animated QR frames (`ur:crypto-psbt`).

In Slice A, we validate the complete stateless execution chain:
$$\text{Secure Boot V2} \rightarrow \text{SD/Flash Ingest} \rightarrow \text{secp256k1 Multisig} \rightarrow \text{TRNG Proof} \rightarrow \text{Cache-MMU Remap} \rightarrow \text{MicroPython} \rightarrow \text{SeedSigner PSBT Sign} \rightarrow \text{UR Export}$$

All signing executes inside the stateless MicroPython payload running from external PSRAM. Host tooling then verifies the resulting signed PSBT against Bitcoin consensus rules and sighash validation.

---

## 2. Test Fixture & Verification Contract (`testqrs.com`)

To ensure realistic SeedSigner testing, Slice A integrates the authentic test vector from [testqrs.com/?tx=ss_native_segwit-change-3in](https://testqrs.com/?tx=ss_native_segwit-change-3in), the official SeedSigner test data suite:

- **Scenario:** `ss_native_segwit-change-3in` (Native SegWit: Send with change, 3 inputs)
- **Signer / Seed:** Alice (24 words, standard test identity)
  - **Mnemonic:** `fence runway woman funny loan vote anxiety alpha neither filter mechanic silent burger sphere athlete visit intact under film frequent manage few wife round`
  - **Master Fingerprint:** `814d5ff8`
  - **Standard SeedQR Payload:** `068015152023075310481967008000561185069111051603024516750113195809401894069007411079068420071507`
  - **Compact SeedQR Payload:** `5517aff3af1831ebc28038942ace28e431eba2c38fa6759d99592e586eab3ebd`
- **Transaction Details:**
  - **Unsigned TXID:** `2a6f31c59e8d351a6d4a4002ce3b1b515d771add6610b21a1d7717f197311ad1`
  - **Inputs:** 3 Native SegWit (P2WPKH) inputs, each 100,000 sats (total: 300,000 sats)
  - **Outputs:**
    - External: `bc1qp75cd269r0m7rt0zgylmu83ge60d3zw3erg4vc` (193,334 sats)
    - Change: `bc1qrvzkqptcvh9trl4seumytkd42e4w0yfxya948s` (96,666 sats)
  - **Fee:** 10,000 sats
  - **Expected Signatures:** 3 valid ECDSA signatures across inputs 0, 1, and 2

### Generated Artifacts (`Phase_23/fixtures/`)

- `fixtures/psbt.txt`: Full base64 unsigned PSBT (551 bytes).
- `fixtures/seedqr.txt`: Standard numeric SeedQR representation for Alice.
- `fixtures/expected.json`: Complete scenario metadata and sighash verification array from `testqrs.com`.
- `fixtures/_headless_fixtures.py`: Frozen fixture module for firmware embedding.

### Verification Criteria (`Phase_23/tools/verify_signed_psbt.py`)

A signed payload output is accepted if and only if:
1. **Txid Match:** The unsigned transaction payload is byte-identical to `testqrs.com` ground truth (`2a6f31c5...`).
2. **Fee & Output Match:** Fee is exactly 10,000 sats and change is 96,666 sats.
3. **Multi-Input ECDSA Signatures:** Each of the 3 inputs carries a valid DER signature matching Alice's derived pubkey and the BIP-143 sighash:
   - Input 0: pubkey `021797a2...`, sighash `c33e33f4...`
   - Input 1: pubkey `0354c348...`, sighash `b2e068f5...`
   - Input 2: pubkey `03f7a5ca...`, sighash `75e50c9e...`
4. **Animated UR Roundtrip:** De-serializes from multi-part `ur:crypto-psbt` fountain frames.

---

## 3. Host Tooling Verification (Tooling Gate Passed)

Before flashing or booting firmware, the roundtrip pipeline was verified host-side:

```sh
python3 tools/host_roundtrip.py
python3 tools/verify_signed_psbt.py build/host_roundtrip/frames.log
```

**Result:**
```text
signed 3 input(s)
encoded 3 UR frame(s), fragment 400 B
wrote build/host_roundtrip/frames.log
decoded UR from 3 frame(s)
ok  unsigned txid unchanged: 2a6f31c59e8d351a6d4a4002ce3b1b515d771add6610b21a1d7717f197311ad1
ok  fee: 10000 sats
ok  input 0 signature from 021797a2ec39ef711b503e4de7828e2cb09e4d0c0588c38b59f4f717f299375001
ok  input 1 signature from 0354c348dbf49e8bd3d6aa579bf2edbbbb6793dc31ca6b0b5bc8ca43202ea0227b
ok  input 2 signature from 03f7a5ca57f11aea8489c5f1036138a049d765d6e67e83da2902ff1826e17123f2

PASS: signed correctly, unsigned data unchanged, no broadcast performed
```

---

## 4. Builder Integration via Clean Patches

To maintain complete isolation and avoid mutating external repositories (`seedsigner-micropython-builder-upstream` and `seedsigner-esp32-bootloader`), all changes are packaged as cleanly applicable and revertible patches under `Phase_23/builder_changes/`:

- `Phase_23/builder_changes/patches/0001-manifest-headless-signer.patch`: Freezes `_headless_fixtures.py` and `_headless_signer.py` in the board manifest.
- `Phase_23/builder_changes/patches/0002-stateless-main-headless-signer.patch`: Invokes `_headless_signer.run()` during early stateless startup before `Controller.start()`.
- `Phase_23/builder_changes/files/frozen_app/`: Holds the staged Python runner and fixtures.
- `Phase_23/builder_changes/apply_changes.sh`: Idempotent script supporting both `./apply_changes.sh` and `./apply_changes.sh --revert`.

---

## 5. Execution & Verification Evidence

The entire pipeline is driven by the automated orchestrator script:
```sh
./Phase_23/tools/run_p4_stateless_sign.sh
```

### 5.1 Bootloader & Stateless Handoff Log
From `Phase_23/logs/p4_emu_stateless_sign.txt`:
```text
I (8) boot: ESP-IDF ac63a927 2nd stage bootloader
I (8) boot: chip revision: v1.3
I (33) esp_image: Verifying image signature...
I (34) secure_boot_v2: Verifying with RSA-PSS...
I (34) secure_boot_v2: Signature verified successfully!
I (37) boot: Loaded app from partition at offset 0x30000
...
I (302) SEEDSIGNER_LOADER: SeedSigner Stateless Loader - Target: seedsigner_esp32p4
I (352) SEEDSIGNER_LOADER: EMU: loaded 4525760 bundle bytes from flash 0x13FF00 (no SD card)
I (352) SEEDSIGNER_LOADER: Specter bootloader section detected
I (352) SEEDSIGNER_LOADER: Firmware version: 1
I (352) SEEDSIGNER_LOADER: Platform matches: seedsigner_esp32p4
I (352) SEEDSIGNER_LOADER: Bundle signature verified! (1 valid key(s) checked)
I (352) SEEDSIGNER_LOADER: Anti-phishing fill skipped (EMU_SKIP_ANTI_PHISH)
I (352) SEEDSIGNER_LOADER: JMP[1]: Disabling cache & interrupts...
I (352) SEEDSIGNER_LOADER: JMP[4]: Cache MMU remap (4521984 bytes)...
I (352) SEEDSIGNER_LOADER: JMP[7]: Jumping to app entry at 0x48000020
```

### 5.2 MicroPython Startup & SeedSigner Headless Signing
```text
[P18] heap add rc=0 free=16250496 largest=15990784
Jumping to esp_startup_start_app...
I (3011) board: Initializing Waveshare ESP32-P4 WiFi6 Touch LCD 4.3...
[HVFB] console ready: dump|tap|swipe|info|result
I (3013) HVFB: headless virtual FB 800x480 (768000 bytes, PSRAM), touch indev ready
[P18] uart_stdout_init: RX ISR skipped (hvfb owns stdin)
[boot-ms] main.py start: 3297
[boot-ms] gc free/alloc pre-import: 15267024 1328
[P23] === Phase 23-A Headless PSBT Signing Starting ===
[P23] Ingested PSBT in 14 ms (txid: 2a6f31c59e8d351a6d4a4002ce3b1b515d771add6610b21a1d7717f197311ad1)
[P23] Ingested Seed in 66 ms (fingerprint: 814d5ff8)
[P23] Parsed PSBT in 28 ms (change: 96666 sats, fee: 10000 sats, inputs: 3)
[P23] Signed PSBT in 49 ms (signatures added: 3)
[P23] QR 0 ur:crypto-psbt/1-2/lpadaocfaobzcydpenwkpdhkadbdhkaobgjojkidjyzmadaesraoaeaeaeaxbebafddmvewtlustnsplwmimmnkiecfszsbdtbcpeccxkihlvevacwpkhechrouraeaeaeaeaezmzmzmzmkposrpstghqdjtrflpbwpyutjyhdtdbwyniaspiobsbbieckksaezesbfxbswtwyaeaeaeaeaezmzmzmzmjtztlejpssswaodrdkfndtgeftfelucplydkchdeoelthphtgywksrfmfpjpbeadaeaeaeaeaezmzmzmzmaoenwfaoaeaeaeaeaecmaebbbsptlnpyfecwylvypmvofpfhrnckdetonntpldttnykkadaeaeaeaeaecmaebbcwahhnahksihsgpazepftkenfetarehfimvdmedsaeaeaeaeaecpaoaochmsoewpeswsjscwgdfmgtvdlfmndwpfnngtbnahlosrluhkwkylchwznlemgdadfldyfyaocxbtcsbsdlqdmkpapfolecgrospswpampmvtesntjpdpesdwme
[P23] QR 1 ur:crypto-psbt/2-2/lpaoaocfaobzcydpenwkpdhkadbdaemugyfrwpbkwlynrftnrowsaocxfnaanepsprgeaygwpafwrnflgymsuosekejpwtlysafpztjtcafhpdmeenbglbatadaecpaoaxghsrfduywknnlutetbpkhgndwzwerkrkiomuuoehsgjebdhpspsgfxcxdmnbcpkgfldyfyaocxatecbyjzwzdefnmncpluveryjewfaycafxrlhnvymwtodmsrclmyrtzsjlahkolpaocxdwesptvydrkpflonahynospfwkonfedkmkhlwnwmuyjyndtlcmathpnduehgaebtadaecpaoaxylonsghgwncywdlrldskwnaxhsetnbgatsihtbvakblstndtaozmcsdsvyjscnwzfldyfyaocxiybyrnaxglgmbwkighwzrnkbjzdiwltiindyrobggmcyhhdywtpkaacyrngdghndaocxglaybkeehtatcncnwdtdrdaoasiaiddeztsfgubgcxjsrklsbddrzmflidurknetadaeaeaeaeiyjepfro
[P23] Exported 2 UR frame(s) in 83 ms
[INFO  esp_emu] Exit-on string '[P23] SUCCESS' found in output
[P23] SUCCESS: full stateless signing flow finished in 288 ms (free heap: 14990752 B)
[INFO  esp_emu] eFuse state saved to '/tmp/emu_ci/efuse_p4_rev1.3.bin'
```

### 5.3 Host Consensus Verification
```text
--> 3. Verifying signed PSBT with host verification script...
decoded UR from 2 frame(s)
ok  unsigned txid unchanged: 2a6f31c59e8d351a6d4a4002ce3b1b515d771add6610b21a1d7717f197311ad1
ok  fee: 10000 sats
ok  input 0 signature from 021797a2ec39ef711b503e4de7828e2cb09e4d0c0588c38b59f4f717f299375001
ok  input 1 signature from 0354c348dbf49e8bd3d6aa579bf2edbbbb6793dc31ca6b0b5bc8ca43202ea0227b
ok  input 2 signature from 03f7a5ca57f11aea8489c5f1036138a049d765d6e67e83da2902ff1826e17123f2

PASS: signed correctly, unsigned data unchanged, no broadcast performed
=== Phase 23 Slice A: VERIFIED SUCCESSFUL ===
```

### 5.4 Physical Silicon Execution (ESP32-P4 Rev 1.3 Hardware)

The signed bundle (`seedsigner_esp32p4.bin`, 4,526,112 bytes) was uploaded straight to the physical microSD card over UART using the loader's RAM-only SD uploader (`tools/sd_upload.py` @ 921600 baud over CH343 bridge, zero flash writes, no card ejection, double SHA-256 verification: `f67816c28d2b1aa439cd62ceb37a1ce60b22d26a7f0adb74dec79c415f268804`).

On hardware reset into the flashed stateless loader:
1. **Secure Boot V2 (Virtual eFuses):** `CONFIG_EFUSE_VIRTUAL=y` verified, virtual eFuse blocks loaded from flash (`0x28000`). Zero physical eFuses burned.
2. **SD Card & Multisig:** MicroSD mounted at `/sdcard`, `seedsigner_esp32p4.bin` loaded into PSRAM and immediately unmounted (anti-TOCTOU). Secp256k1 multisig verification **PASSED**.
3. **Anti-Phishing Proof:** Flash-fill hash verified: `ANTI-PHISHING PROOF: wonder echo bomb balcony`.
4. **Stateless PSRAM JMP:** 8 segments mapped; jumped into MicroPython.
5. **App Pipeline Execution:** Headless signing engine executed:
   - Ingested PSBT in 26 ms (txid `2a6f31c5...1ad1`)
   - Ingested Alice seed in 165 ms (fingerprint `814d5ff8`)
   - Parsed PSBT in 47 ms (3 inputs, change 96,666 sats, fee 10,000 sats)
   - Signed PSBT in 82 ms (3 ECDSA secp256k1 signatures added)
   - Exported 2 animated UR frames in 221 ms
   - Full stateless signing flow finished in **631 ms** (free heap in PSRAM: **14,990,736 B** / ~14.30 MB).
6. **Host Consensus:** `verify_signed_psbt.py Phase_23/logs/p4_hw_stateless_sign.txt` passed with all 3 signatures verified against BIP-143 sighashes and testqrs.com pubkeys. Evidence logged in [`Phase_23/logs/p4_hw_stateless_sign.txt`](./logs/p4_hw_stateless_sign.txt).

---

### 5.5 ESP32-S3 Execution in `esp-emu` (Xtensa LX7 Architecture)

Phase 23 was also ported and verified on the **ESP32-S3** (`WAVESHARE_ESP32_S3_TOUCH_LCD_35B`) in `esp-emu` v0.50.0. Prior to this, Phase 16/17 had only run the bare MicroPython interactive REPL (`print(5 + 6)`). This marks the **first time the genuine SeedSigner application stack and Bitcoin PSBT signing pipeline have run on the ESP32-S3 stateless bootloader**.

#### S3 Architectural Adaptations:
1. **Builder Overlay ([`Phase_23/builder_changes_s3/`](./builder_changes_s3/)):**
   - Configured `MICROPY_FROZEN_MANIFEST` in `mpconfigboard.cmake` to freeze `seedsigner`, `embit`, `urtypes`, and test fixtures into bytecode.
   - Wired `_boot.py` hook to execute `_headless_signer.run()`.
2. **PSRAM External Malloc Enabling ([`0002-s3-stateless-shim-extmem.patch`](./builder_changes_s3/patches/0002-s3-stateless-shim-extmem.patch)):**
   - ESP-IDF defaults `malloc_alwaysinternal_limit` to `MALLOC_DISABLE_EXTERNAL_ALLOCS` (-1), blocking `malloc()` from allocating in external memory.
   - S3 `stateless_shim.c` calls `heap_caps_malloc_extmem_enable(16384)` after registering the 5 MB PSRAM heap region (`0x3C300000`-`0x3C800000`), allowing MicroPython's auto split-heap allocator (`gc_try_add_heap`) to dynamically expand into PSRAM.
3. **Execution Output:**
   ```text
   === STATELESS SHIM S3 MICROPYTHON PAYLOAD BOOT OK ===
   === __wrap_call_start_cpu0 ENTERED ===
   BSS cleared.
   Calling clocks init...
   Clocks initialized and interrupt matrix cleared.
   Initializing MMU software contexts...
   Calling init functions...
   Running global constructors...
   Manually adding PSRAM to heap...
   Jumping to esp_startup_start_app...
   [P23] === Phase 23-A Headless PSBT Signing Starting ===
   [P23] Ingested PSBT in 24 ms (txid: 2a6f31c59e8d351a6d4a4002ce3b1b515d771add6610b21a1d7717f197311ad1)
   [P23] Ingested Seed in 100 ms (fingerprint: 814d5ff8)
   [P23] Parsed PSBT in 58 ms (change: 96666 sats, fee: 10000 sats, inputs: 3)
   [P23] Signed PSBT in 108 ms (signatures added: 3)
   [P23] QR 0 ur:crypto-psbt/1-2/lpadaocfaobzcydpenwkpdhkadbdhkaobgjojkidjyzmadaesraoaeaeaeaxbebafddmvewtlustnsplwmimmnkiecfszsbdtbcpeccxkihlvevacwpkhechrouraeaeaeaeaezmzmzmzmkposrpstghqdjtrflpbwpyutjyhdtdbwyniaspiobsbbieckksaezesbfxbswtwyaeaeaeaeaezmzmzmzmjtztlejpssswaodrdkfndtgeftfelucplydkchdeoelthphtgywksrfmfpjpbeadaeaeaeaeaezmzmzmzmaoenwfaoaeaeaeaeaecmaebbbsptlnpyfecwylvypmvofpfhrnckdetonntpldttnykkadaeaeaeaeaecmaebbcwahhnahksihsgpazepftkenfetarehfimvdmedsaeaeaeaeaecpaoaochmsoewpeswsjscwgdfmgtvdlfmndwpfnngtbnahlosrluhkwkylchwznlemgdadfldyfyaocxbtcsbsdlqdmkpapfolecgrospswpampmvtesntjpdpesdwme
   [P23] QR 1 ur:crypto-psbt/2-2/lpaoaocfaobzcydpenwkpdhkadbdaemugyfrwpbkwlynrftnrowsaocxfnaanepsprgeaygwpafwrnflgymsuosekejpwtlysafpztjtcafhpdmeenbglbatadaecpaoaxghsrfduywknnlutetbpkhgndwzwerkrkiomuuoehsgjebdhpspsgfxcxdmnbcpkgfldyfyaocxatecbyjzwzdefnmncpluveryjewfaycafxrlhnvymwtodmsrclmyrtzsjlahkolpaocxdwesptvydrkpflonahynospfwkonfedkmkhlwnwmuyjyndtlcmathpnduehgaebtadaecpaoaxylonsghgwncywdlrldskwnaxhsetnbgatsihtbvakblstndtaozmcsdsvyjscnwzfldyfyaocxiybyrnaxglgmbwkighwzrnkbjzdiwltiindyrobggmcyhhdywtpkaacyrngdghndaocxglaybkeehtatcncnwdtdrdaoasiaiddeztsfgubgcxjsrklsbddrzmflidurknetadaeaeaeaeiyjepfro
   [P23] Exported 2 UR frame(s) in 199 ms
   [P23] SUCCESS: full stateless signing flow finished in 570 ms (free heap: 4912608 B)
   ```
4. **Host Consensus Verification:**
   ```text
   $ python3 Phase_23/tools/verify_signed_psbt.py Phase_23/logs/s3_emu_stateless_sign.txt
   decoded UR from 2 frame(s)
   ok  unsigned txid unchanged: 2a6f31c59e8d351a6d4a4002ce3b1b515d771add6610b21a1d7717f197311ad1
   ok  fee: 10000 sats
   ok  input 0 signature from 021797a2ec39ef711b503e4de7828e2cb09e4d0c0588c38b59f4f717f299375001
   ok  input 1 signature from 0354c348dbf49e8bd3d6aa579bf2edbbbb6793dc31ca6b0b5bc8ca43202ea0227b
   ok  input 2 signature from 03f7a5ca57f11aea8489c5f1036138a049d765d6e67e83da2902ff1826e17123f2

   PASS: signed correctly, unsigned data unchanged, no broadcast performed
   ```
   Full log recorded in [`Phase_23/logs/s3_emu_stateless_sign.txt`](./logs/s3_emu_stateless_sign.txt).

---

## 6. Performance & Memory Benchmarks

All operations executed directly in external PSRAM under Cache-MMU mapping:

| Target & Environment | Architecture | PSRAM Size | PSBT Ingest | Seed Ingest | Parse | Sign (3 inputs) | UR Export | Total Time | Free Heap at Exit |
|---|---|---|---|---|---|---|---|---|---|
| **ESP32-P4 (esp-emu)** | RISC-V RV32IMAFCP | 32 MB | 14 ms | 66 ms | 28 ms | 49 ms | 83 ms | **288 ms** | 14,990,752 B (~14.3 MB) |
| **ESP32-P4 (Physical Silicon)** | RISC-V RV32IMAFCP | 32 MB | 26 ms | 165 ms | 47 ms | 82 ms | 221 ms | **631 ms** | 14,990,736 B (~14.3 MB) |
| **ESP32-S3 (esp-emu)** | Xtensa LX7 | 8 MB | 24 ms | 100 ms | 58 ms | 108 ms | 199 ms | **570 ms** | 4,912,608 B (~4.91 MB) |
