# HEADLESS_VIRTUAL_FB for esp-board-common (upstream-main bring-up)

- **Status:** PROVEN on P4 DEV-KIT silicon (Oct 14, 2026) - applied in the
  pristine upstream-main clone at `~/Desktop/seedsigner-micropython-builder-upstream`
  (`_local_ws/esp-board-common` build copy; the `wolgwang1729` fork checkout was
  never touched). `touch_test` (`waveshare_p4_lcd43` + `HEADLESS_VIRTUAL_FB=1`)
  boots headless: `HEADLESS_VIRTUAL_FB active: display+touch virtualised`.
- **Execution model:** normal flash execution (app runs from flash, PSRAM is
  plain heap for the framebuffer). The stateless secure bootloader (PSRAM XIP
  execution) is NOT involved - deliberately, so display/touch comes up first.
- **External file (upstream main, lines moved vs the fork):**
  `ports/esp32/board_common/src/board_init.c`
  (`lvgl_port_setup` ~line 1053, display init ~line 1536, touch init ~line 1579).
- **This folder:** `headless_virtual_fb.h` / `headless_virtual_fb.c` - self-contained
  virtual display + emulated-touch unit, logic copied from the P4-silicon-proven
  `virtual_fb_demo/main/{virtual_fb_demo,console_fb}.c`.

## 1. Why this exists

The DEV-KIT is headless (no ST7701/GT911), but the `waveshare_p4_lcd43` target is
natively 480x800 portrait - exactly our virtual-FB geometry. On the DEV-KIT,
`panel_handle` and `touch_handle` stay NULL, so `board_init()` returns
`disp=NULL, touch=NULL` and `touch_test` cannot run. This draft fills both with
virtual equivalents: PSRAM framebuffer + UART stream (display) and a
pointer-type `lv_indev` fed by console lines (touch). Apps (`touch_test`,
later `seedsigner-lvgl-screens`) need no headless special case - coordinates
stay in GT911 firmware-pixel space.

Explicitly out of scope: camera pipeline, secure bootloader, any eFuse/secure-boot
provisioning. See `Phase_18_Virtual_Display_DevKit.md` honest limits.

## 2. Hook (upstream main - applied as follows)

In `board_init.c`:

1. Include (guarded, next to the other includes):
   ```c
   #ifdef HEADLESS_VIRTUAL_FB
   #include "headless_virtual_fb.h"
   #endif
   ```
2. Step 3 display init - skip ST7701 under the flag (leaves `panel_handle`
   NULL instead of aborting in `ESP_ERROR_CHECK`):
   ```c
   #elif BOARD_DISPLAY_DRIVER == DISPLAY_ST7701
   #ifdef HEADLESS_VIRTUAL_FB
       ESP_LOGW(TAG, "HEADLESS_VIRTUAL_FB: ST7701 init skipped (headless DEV-KIT)");
   #else
       board_display_st7701_init(&io_handle, &panel_handle);
   #endif
   #endif
   ```
3. Step 5 GT911 touch init - same treatment (leaves `touch_handle` NULL):
   ```c
   #elif BOARD_TOUCH_DRIVER == TOUCH_GT911
   #ifdef HEADLESS_VIRTUAL_FB
       ESP_LOGW(TAG, "HEADLESS_VIRTUAL_FB: GT911 init skipped (emulated touch)");
       touch_handle = NULL;
   #else
       touch_handle = board_touch_gt911_init(i2c_bus, touch_x_max, touch_y_max);
       ...
   #endif
   #endif
   ```
4. `lvgl_port_setup`, right after `lvgl_port_init` - virtual display + indev,
   early-return so no panel path runs (outputs pre-nulled because callers
   pass uninitialised stack slots):
   ```c
   #ifdef HEADLESS_VIRTUAL_FB
       if (disp_out)  *disp_out  = NULL;
       if (touch_out) *touch_out = NULL;
    if (panel_handle == NULL) {
        if (hvfb_init_ex(disp_out, touch_out, landscape ? 1 : 0) == 0) {
            ESP_LOGI(TAG, "HEADLESS_VIRTUAL_FB active: display+touch virtualised");
            return;
        }
        ESP_LOGW(TAG, "HEADLESS_VIRTUAL_FB init failed; falling back to panel path");
    }
   #endif
   ```

Plus, in the component `CMakeLists.txt`: `src/headless_virtual_fb.c` appended
to `SRC_FILES` and `target_compile_definitions(${COMPONENT_LIB} PUBLIC
HEADLESS_VIRTUAL_FB=1)` - both inside `if(HEADLESS_VIRTUAL_FB)`, enabled with
`idf.py -DHEADLESS_VIRTUAL_FB=1 build` (off by default, stock behaviour kept).

Bring-up fixes the silicon run surfaced (all inside the `_local_ws` copy -
tracked upstream files untouched except the hook above):
- LVGL is 9.6: `lv_indev_set_read_cb` takes 2 args (draft had 3).
- Upstream `main` has no headless fallback (unlike the fork branch) - hence
  guards 2-4; without them the boot aborts in display init.
- Upstream `main` P4 app builds need two copy-local fixes: the app's
  `EXTRA_COMPONENT_DIRS` omits `../../components`, so `ov02c10` (REQUIREd on
  P4) never resolves - flagged for Keith; and the bootloader exceeds
  0x6000, so the copy uses ptable @0x10000 with nvs/phy/factory relayed to
  0x11000/0x17000/0x20000.
- Copy-local silicon deltas for the v1.3 16MB DEV-KIT: board sdkconfig flash
  32MB -> 16MB, `CONFIG_ESP32P4_SELECTS_REV_LESS_V3=y`. Restore when targeting
  the real 4.3" panel board.

## 3. Console protocol (device side)

```
dump                  -> FB_BEGIN w h len crc32hex, 4000x FB_CHUNK, FB_END
tap <x> <y>           -> 150 ms press+release pulse at (x,y), clamped to FB
swipe <x0> <y0> <x1> <y1> -> 8-step linear press/move/release (~320 ms)
info                  -> [HVFB] fb WxH len= crc= free=
result                -> hvfb_result_print() (weak no-op; screens apps override
                         to report the last selection - instant tap proof)
```

`tools/fb_live.py` already speaks the stream side and now sends
`tap` (window click) / `swipe` (window drag) with firmware-pixel coordinates -
see `display_to_fw()` / `format_tap()` / `format_swipe()` and
`tests/test_fb_live.py` for the mirrored parser tests.

## 4. Reversibility statement (read before any flash)

- RAM + UART only. No `espefuse.py` / `idf.py efuse` / burn commands anywhere.
- No partition-table edits, no bootloader changes, no OTP/revision-lock writes.
- Applying = copy two files + 5-line hook + build flag. Reverting = `git checkout`
  in the builder repo. Flashing `touch_test` to the DEV-KIT is a plain reversible
  `idf.py flash` (same class of operation as `virtual_fb_demo/run.sh`).
- Nothing in this folder touches the secure bootloader chain (Phases 12/13/17).

## 5. Acceptance (verified Oct 14, 2026, P4 DEV-KIT v1.3 silicon)

1. `idf.py -DBOARD=waveshare_p4_lcd43 -DHEADLESS_VIRTUAL_FB=1 build` [PASS]
   (`touch_test.bin` 0xbd260 and `seedsigner_screen_test.bin` 0x1158e0,
   local IDF v5.5.5, LVGL 9.6.0).
2. Plain reversible flash to the headless DEV-KIT [PASS] - boots to
   `HEADLESS_VIRTUAL_FB active` + app running, no abort.
3. `touch_test` (portrait 480x800): corner buttons + icosahedron stream,
   CRC OK [PASS]; click = tap (button ACTIVE flash), drag = swipe [PASS].
4. `seedsigner_screen_test` (landscape 800x480, Option A): real
   `button_list_screen` (Dog/Cat/Fish) streams CRC-OK [PASS]; window click on
   Cat -> `[HVFB] result: button_selected #1 'Cat'` [PASS]. (Buttons show only a
   transient ~150 ms press flash, no latched highlight - the `result`
   readout is the persistent proof.)
5. Undefine the flag -> stock panel behaviour (aborts headless, as before).
