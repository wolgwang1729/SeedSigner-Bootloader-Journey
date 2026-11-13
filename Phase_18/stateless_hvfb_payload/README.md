# Stateless HVFB payload (Phase 18, slice 1)

**Status:** SILICON-PROVEN Oct 15, 2026 (P4 DEV-KIT v1.3) - see
`Phase_18_Virtual_Display_DevKit.md` for the full boot log: Secure Boot V2
-> SD bundle verify -> multisig PASSED -> anti-phishing words -> JMP -> shim ->
LVGL console + button pad, taps via UART, CRC-OK dump (`fb_stateless_hvfb.png`).

Signed stateless payload proving the **display hack under PSRAM execution**:
LVGL renders into a 480x800 RGB565 PSRAM framebuffer while the CPU executes
the verified image from PSRAM via the loader's Cache-MMU remap - no flash
execution, no panel hardware.

## Layout

| Path | Contents |
|---|---|
| `main/stateless_hvfb_main.c` | `app_main`: chip info -> `hvfbs_init()` -> idle |
| `main/hvfb_stateless.h/.c` | Virtual display + pointer indev + console + UART streamer. `lv_init()` + esp_timer tick + private LVGL task (the `console_fb.c` pattern - **no `esp_lvgl_port`**, which the shim payload does not link). UI: transcript + 2x2 `BTN_A..D` pad |
| `components/stateless_shim/` | Stateless shim implementation (`my_entry_point`, CLIC vectors, `__wrap_*` early-boot skips) |
| `sdkconfig.defaults` | Stock-shim PSRAM-XIP prereqs + `CONFIG_LV_FONT_UNSCII_8=y` (transcript font). Never enable `MINIMAL_BUILD` |
| `build_sign.sh` | Build -> Specter-sign (`seedsigner_esp32p4`, test profile) -> `../build/seedsigner_esp32p4.bin` |

## Bring-up

```bash
./build_sign.sh
~/Desktop/seedsigner-esp32-bootloader/run.sh --target esp32p4 upload-sd ../build/seedsigner_esp32p4.bin
python3 ../tools/fb_live.py --baud 115200   # Dump, then click = tap
```

Console (115200): `dump | tap x y | swipe x0 y0 x1 y1 | info | result`.
`result` prints the last pad selection - the durable tap proof (buttons only
flash ~150 ms while pressed). A full `dump` is ~95 s at this baud; taps and
`result` are instant.

## Prerequisites

- Desktop loader flashed for P4 with test keys (`run.sh --target esp32p4 flash`).
  `run.sh` refuses to flash unless `CONFIG_EFUSE_VIRTUAL=y` - flash writes
  only, no eFuse operations anywhere in this slice.
- `python3 -c 'import ecdsa, bech32'` for the signer.
