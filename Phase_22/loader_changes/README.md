# Phase 22 - Loader Compatibility Patch

`kern-image-compat.patch` applies to a **scratch copy** of the loader after the
Phase 21 emulator overlay:

```sh
git -C ../seedsigner-esp32-bootloader checkout 976ee3a
cp -r ../seedsigner-esp32-bootloader /tmp/loader
patch -d /tmp/loader -p1 < Phase_21/loader_changes/emu-flash-payload.patch
patch -d /tmp/loader -p1 < Phase_22/loader_changes/kern-image-compat.patch
```

It is additive; the production verification path is untouched. What it does:

| Change | Why |
|---|---|
| Skip IDF 6.x zero-address padding segments in both image-parser passes, advancing `offset` by `seg.data_len` | The v5.5 parser rejected the padding block IDF 6.1 emits before the signature section. The offset advance is mandatory: without it the next segment header is read 36 bytes early. |
| Skip payload RTC/LP-RAM segments that overlap the loader's `_rtc_text_start.._rtc_text_end` JMP code (P4 only), with a loud warning, before `MAX_DIRECT_COPIES` accounting | Kern's 36-byte `.rtc.force_slow` segment lands exactly on `do_mmu_mapping_and_jump` (`0x50108080`); copying it overwrote the code doing the copy (`Illegal instruction ... PC=0x50108080`). A payload that truly needs RTC state must be rejected, not silently truncated. |
| Accepted-platform table (`storage.h`: `ACCEPTED_PLATFORMS`) and `platform_accepted()` in `main.c` | The loader was hardcoded to `seedsigner_esp32p4`. The table accepts SeedSigner P4/S3 plus `kern_esp32p4` and `specter_esp32p4`. The bundle platform string is now logged (`Platform accepted: ...`). |
| SD-card filename fallback (`SD_FIRMWARE_PATHS` on P4) | Tries `seedsigner_esp32p4.bin`, then `kern_esp32p4.bin`, then `specter_esp32p4.bin`. |
| `tools/generate_signed_payload.py` platform choices | Adds `kern_esp32p4` and `specter_esp32p4`. |

Not included: per-platform signing keys. The current test bundle still uses the
shared `test` profile key; the platform string is a binding check, not project
isolation. That remains a Phase 22 item.

The full clean build + sign + merge + emu flow is automated in
`Phase_22/tools/build_kern_stateless_emu.sh`.
