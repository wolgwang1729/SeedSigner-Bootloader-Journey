/*
 * canary_scrub — Phase 19 G1 test payload (C-only, signed bundle).
 *
 * Plants fixed-region secrets (1 MB PSRAM window + 4 KB on-chip SRAM),
 * installs panic/WDT scrub hooks, and faults on UART command. The loader's
 * early inspector (pre-SD-load) reports CANARY_REMANENT (control) vs
 * CANARY_CLEARED (patched) for the PSRAM window on the next boot; the
 * payload self-reports the SRAM secret (linker-reserved noinit, so it
 * survives warm reset and is never heap-reused).
 *
 * UART commands (newline-terminated):
 *   plant          — set RTC test magic + fill PSRAM (1 MB) + SRAM (4 KB)
 *   scrub_on/off   — toggle the scrub hooks (control vs patched)
 *   status         — print scrub flag, magic, PSRAM/SRAM heads + XOR, telemetry
 *   selftest       — plant, wipe live (NO reset), verify zeros, stack
 *                    round-trip; proves the loop + switch mechanism live
 *   fault_abort    — abort()  -> ESP_RST_PANIC  (via __wrap_esp_restart_noos)
 *   fault_restart  — esp_restart() -> ESP_RST_SW (via shutdown handler)
 *   fault_wdt      — interrupts off + spin -> INT_WDT (via noos wrapper)
 *   fault_hpwdt    — MWDT0 system reset (pure hardware, NO hook runs;
 *                    expect REMANENT even with scrub on — boundary proof)
 *
 * Scrub architecture: wipe PSRAM + SRAM on the live stack, then switch SP
 * onto a dedicated reserve stack, wipe the old task-stack window, flush,
 * record telemetry, and reset directly via __real_esp_restart_noos (both
 * paths are noreturn — the shutdown handler does NOT return into
 * esp_restart; there is nothing left to return to). The 8 KB stack wipe is
 * covered by construction + timing + selftest round-trip (a live stack has
 * no cross-reset oracle by definition).
 *
 * Mock entropy only — never a real seed.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_cpu.h"
#include "esp_rom_sys.h"
#include "hal/wdt_hal.h"
#include "soc/timer_group_struct.h"

#if CONFIG_IDF_TARGET_ESP32P4
#define CANARY_ADDR ((volatile uint32_t *)0x48400000)
#define MAGIC_ADDR  ((volatile uint32_t *)0x5010FFF0)
#elif CONFIG_IDF_TARGET_ESP32S3
#define CANARY_ADDR ((volatile uint32_t *)0x3C7F0000)
#define MAGIC_ADDR  ((volatile uint32_t *)0x600FFFF0)
#else
#error "Unsupported target for canary_scrub"
#endif
#define MAGIC_WORD_ADDR (MAGIC_ADDR + 0)

// Stable cross-reset telemetry + SRAM secret at FIXED top-of-RTC addresses.
// (An earlier revision used RTC_NOINIT_ATTR, but the payload's RTC heap pool
// starts exactly at .rtc_noinit's VMA (0x50108080), so heap creation
// clobbered it deterministically. Fixed top-zone words are empirically
// stable instead — validated by pattern-exact readbacks across runs.)
#if CONFIG_IDF_TARGET_ESP32P4
#define SRAM_SECRET_ADDR ((volatile uint32_t *)0x5010E000)  // 4 KB, ends 0x5010F000
#define TELEMETRY_ADDR   ((volatile uint32_t *)0x5010FFE0)  // fired, cycles
#elif CONFIG_IDF_TARGET_ESP32S3
// S3 placement provisional: validate against the S3 RTC heap map before use.
#define SRAM_SECRET_ADDR ((volatile uint32_t *)0x600FE000)  // 4 KB
#define TELEMETRY_ADDR   ((volatile uint32_t *)0x600FFFE0)
#endif
#define SCRUB_FIRED_WORD  (TELEMETRY_ADDR + 0)
#define SCRUB_CYCLES_WORD (TELEMETRY_ADDR + 1)
#define SRAM_WORDS 1024

#define CANARY_LEN    (1024 * 1024)
#define CANARY_WORDS  (CANARY_LEN / 4)
#define CANARY_PATTERN32 ((uint32_t)0xCA4A5EEDu)
#define SRAM_PATTERN32   ((uint32_t)0x5EC5EC5Eu)
#define RTC_TEST_MAGIC   ((uint32_t)0xCA19CA19)

// Bottom-half wipe of the 16 KB main-task stack (oldest frames; the live
// top half is abandoned the moment SP switches — nothing returns).
#define STACK_WIPE_LEN 8192
static uint8_t s_scrub_stack[8192] __attribute__((aligned(16)));
static volatile uint8_t *s_wipe_start;
static volatile size_t s_wipe_len;
static volatile uint32_t s_t0;
static volatile uint32_t s_switch_marker;

static volatile int g_scrub_enabled = 1;

extern int Cache_WriteBack_Addr(uint32_t map, uint32_t vaddr, uint32_t size);

static void IRAM_ATTR psram_flush(void)
{
    Cache_WriteBack_Addr(0x10, (uint32_t)CANARY_ADDR, CANARY_LEN);
    Cache_WriteBack_Addr(0x20, (uint32_t)CANARY_ADDR, CANARY_LEN);
    __asm__ volatile("fence rw,rw" ::: "memory");
}

// Phase 19 finding: the P4 L1 D-cache is write-back — zeros issued right
// before reset linger in cache and never land in PSRAM (first patched runs
// still showed REMANENT). The ROM write-back below forces them out before
// the caller resets. Internal SRAM (L2MEM/RTC) is directly accessed
// (uncached), so plain volatile stores suffice there.
static void IRAM_ATTR wipe_psram(void)
{
    volatile uint32_t *p = CANARY_ADDR;
    for (size_t i = 0; i < CANARY_WORDS; i++) {
        p[i] = 0;
    }
    __asm__ volatile("" ::: "memory");
    psram_flush();
}

static void IRAM_ATTR wipe_sram(void)
{
    volatile uint32_t *s = SRAM_SECRET_ADDR;
    for (size_t i = 0; i < SRAM_WORDS; i++) {
        s[i] = 0;
    }
    __asm__ volatile("" ::: "memory");
}

// Count nonzero words in the SRAM secret (fixed address: readable anytime,
// any boot — the cross-reset SRAM oracle).
static uint32_t sram_nonzero(void)
{
    volatile uint32_t *s = SRAM_SECRET_ADDR;
    uint32_t n = 0;
    for (size_t i = 0; i < SRAM_WORDS; i++) {
        if (s[i] != 0) {
            n++;
        }
    }
    return n;
}

// Runs on the reserve stack (old stack already abandoned). Wipes the old
// task-stack window, records telemetry, resets. Never returns.
static void IRAM_ATTR __attribute__((noreturn)) scrub_phase2(void)
{
    volatile uint8_t *p = s_wipe_start;
    size_t n = s_wipe_len;
    for (size_t i = 0; i < n; i++) {
        p[i] = 0;
    }
    __asm__ volatile("" ::: "memory");
    extern void __real_esp_restart_noos(void);
    uint32_t t1 = esp_cpu_get_cycle_count();
    SCRUB_CYCLES_WORD[0] = t1 - s_t0;
    SCRUB_FIRED_WORD[0] = 1;
    __asm__ volatile("" ::: "memory");
    __real_esp_restart_noos();
    while (1) {
    }
}

// Point of no return: wipe PSRAM + SRAM on the live stack, stash the old
// stack window in globals (never stack locals past this point), switch SP
// onto the reserve, and continue in scrub_phase2.
static void IRAM_ATTR scrub_and_die(void)
{
    portDISABLE_INTERRUPTS();
    uint32_t t0 = esp_cpu_get_cycle_count();
    wipe_psram();
    wipe_sram();
    uint8_t *st = pxTaskGetStackStart(xTaskGetCurrentTaskHandle());
    s_wipe_start = st;
    s_wipe_len = STACK_WIPE_LEN;
    s_t0 = t0;
    __asm__ volatile("" ::: "memory");
#if CONFIG_IDF_TARGET_ESP32P4
    __asm__ volatile("mv sp, %0" :: "r"(s_scrub_stack + sizeof(s_scrub_stack)) : "memory");
#elif CONFIG_IDF_TARGET_ESP32S3
    // Plain C assignment to a1 is a dead store under Xtensa GCC (Phase 15);
    // inline asm survives.
    __asm__ volatile("mov a1, %0" :: "r"(s_scrub_stack + sizeof(s_scrub_stack)) : "memory");
#endif
    scrub_phase2();
    __builtin_unreachable();
}

static void scrub_shutdown_handler(void)
{
    // Control runs return so esp_restart() proceeds normally; patched runs
    // never come back (there is no live stack left to return to — reset
    // directly, which is all esp_restart would do next anyway).
    if (!g_scrub_enabled) {
        return;
    }
    scrub_and_die();
}

// Panic/abort/task-WDT path on IDF v5.5 goes through esp_restart_noos(),
// which skips shutdown handlers. Intercept it here (linked with
// -Wl,--wrap=esp_restart_noos).
extern void __real_esp_restart_noos(void);
void __wrap_esp_restart_noos(void)
{
    if (!g_scrub_enabled) {
        __real_esp_restart_noos();
        return;
    }
    scrub_and_die();
}

static void IRAM_ATTR plant_psram(void)
{
    volatile uint32_t *p = CANARY_ADDR;
    for (size_t i = 0; i < CANARY_WORDS; i++) {
        p[i] = CANARY_PATTERN32 ^ (uint32_t)i;
    }
    __asm__ volatile("" ::: "memory");
    // Flush the pattern out to physical PSRAM (write-back cache), so the
    // loader inspector observes the plant and not a cache artifact.
    psram_flush();
}

static void do_plant(void)
{
    MAGIC_WORD_ADDR[0] = RTC_TEST_MAGIC;
    SCRUB_FIRED_WORD[0] = 0;
    SCRUB_CYCLES_WORD[0] = 0;
    plant_psram();
    volatile uint32_t *s = SRAM_SECRET_ADDR;
    for (size_t i = 0; i < SRAM_WORDS; i++) {
        s[i] = SRAM_PATTERN32 ^ (uint32_t)i;
    }
    __asm__ volatile("" ::: "memory");
    printf("CANARY_PLANTED addr=0x%08lX len=%d pattern=0x%08lX sram=0x%08lX\n",
           (unsigned long)CANARY_ADDR, (int)CANARY_LEN,
           (unsigned long)CANARY_PATTERN32, (unsigned long)SRAM_PATTERN32);
    fflush(stdout);
}

static uint32_t psram_xor(void)
{
    volatile uint32_t *p = CANARY_ADDR;
    uint32_t x = 0;
    for (size_t i = 0; i < CANARY_WORDS; i++) {
        x ^= p[i];
    }
    return x;
}

static void do_status(void)
{
    volatile uint32_t *p = CANARY_ADDR;
    volatile uint32_t *s = SRAM_SECRET_ADDR;
    printf("STATUS scrub=%s magic=0x%08lX psram[0]=0x%08lX psram[1]=0x%08lX "
           "psram_xor=0x%08lX sram[0]=0x%08lX sram_nonzero=%lu fired=%lu cycles=%lu\n",
           g_scrub_enabled ? "on" : "off",
           (unsigned long)MAGIC_WORD_ADDR[0],
           (unsigned long)p[0], (unsigned long)p[1],
           (unsigned long)psram_xor(),
           (unsigned long)s[0], (unsigned long)sram_nonzero(),
           (unsigned long)SCRUB_FIRED_WORD[0],
           (unsigned long)SCRUB_CYCLES_WORD[0]);
    fflush(stdout);
}

// Live (no-reset) proof of the wipe loop + stack-switch mechanism. Plants,
// wipes (no reset, no stack wipe — the stack is live), verifies zeros, then
// a save/switch/touch/restore round-trip on the reserve stack.
static void do_selftest(void)
{
    int ok = 1;
    plant_psram();
    volatile uint32_t *s = SRAM_SECRET_ADDR;
    for (size_t i = 0; i < SRAM_WORDS; i++) {
        s[i] = SRAM_PATTERN32 ^ (uint32_t)i;
    }
    // Non-vacuous precondition: the patterns must be observable BEFORE the
    // wipe (a bare XOR-fold would be 0 for these patterns even unscrubbed).
    volatile uint32_t *p = CANARY_ADDR;
    if (p[0] != CANARY_PATTERN32 || p[CANARY_WORDS - 1] != (CANARY_PATTERN32 ^ (uint32_t)(CANARY_WORDS - 1)) ||
        s[0] != SRAM_PATTERN32 || s[SRAM_WORDS - 1] != (SRAM_PATTERN32 ^ (uint32_t)(SRAM_WORDS - 1))) {
        printf("SELFTEST plant NOT observable (precondition failed)\n");
        ok = 0;
    }
    wipe_psram();
    wipe_sram();
    // Explicit-word postcondition (head/mid/tail of each region).
    if (p[0] != 0 || p[1] != 0 || p[CANARY_WORDS / 2] != 0 || p[CANARY_WORDS - 1] != 0 ||
        s[0] != 0 || s[1] != 0 || s[SRAM_WORDS / 2] != 0 || s[SRAM_WORDS - 1] != 0) {
        printf("SELFTEST wipe NOT zero (p0=0x%08lX s0=0x%08lX)\n",
               (unsigned long)p[0], (unsigned long)s[0]);
        ok = 0;
    }
    // Stack-switch round-trip via globals only (sp-relative locals would
    // address the wrong stack mid-test).
    s_switch_marker = 0xBEEFBEEF;
#if CONFIG_IDF_TARGET_ESP32P4
    uint32_t saved_sp;
    __asm__ volatile("mv %0, sp" : "=r"(saved_sp));
    __asm__ volatile("mv sp, %0" :: "r"(s_scrub_stack + sizeof(s_scrub_stack)) : "memory");
    s_scrub_stack[0] = 0xAA;
    s_scrub_stack[sizeof(s_scrub_stack) - 1] = 0x55;
    __asm__ volatile("mv sp, %0" :: "r"(saved_sp) : "memory");
#elif CONFIG_IDF_TARGET_ESP32S3
    uint32_t saved_sp;
    __asm__ volatile("mov %0, a1" : "=r"(saved_sp));
    __asm__ volatile("mov a1, %0" :: "r"(s_scrub_stack + sizeof(s_scrub_stack)) : "memory");
    s_scrub_stack[0] = 0xAA;
    s_scrub_stack[sizeof(s_scrub_stack) - 1] = 0x55;
    __asm__ volatile("mov a1, %0" :: "r"(saved_sp) : "memory");
#endif
    if (s_switch_marker != 0xBEEFBEEF || s_scrub_stack[0] != 0xAA ||
        s_scrub_stack[sizeof(s_scrub_stack) - 1] != 0x55) {
        printf("SELFTEST stack round-trip FAILED\n");
        ok = 0;
    }
    // Clear the plant's test magic so a later manual reset isn't mistaken
    // for a campaign boot.
    MAGIC_WORD_ADDR[0] = 0;
    printf("SELFTEST_%s\n", ok ? "OK" : "FAIL");
    fflush(stdout);
}

void app_main(void)
{
    esp_err_t r = esp_register_shutdown_handler(scrub_shutdown_handler);
    printf("[canary] shutdown handler %s\n", r == ESP_OK ? "registered" : "NOT registered");
    printf("[canary] CANARY TEST PAYLOAD — commands: plant, scrub_on, scrub_off, "
           "status, selftest, fault_abort, fault_restart, fault_wdt, fault_hpwdt\n");
    // Cross-reset report. Fixed top-zone words: empirically stable across
    // boots (unlike heap-pool-backed noinit). Anything else up here would
    // be heap-reused garbage by now.
    if (SCRUB_FIRED_WORD[0] == 1) {
        uint32_t us = SCRUB_CYCLES_WORD[0] / 360;  // 360 MHz P4 HP CPU
        printf("[canary] last scrub fired, cycles=%lu (~%lu us), sram_nonzero=%lu\n",
               (unsigned long)SCRUB_CYCLES_WORD[0], (unsigned long)us,
               (unsigned long)sram_nonzero());
        SCRUB_FIRED_WORD[0] = 0;
    } else {
        printf("[canary] sram_nonzero=%lu (1024 means SRAM retained)\n",
               (unsigned long)sram_nonzero());
    }
    fflush(stdout);

    char line[64];
    printf("> ");
    fflush(stdout);
    while (1) {
        if (!fgets(line, sizeof(line), stdin)) {
            vTaskDelay(100 / portTICK_PERIOD_MS);
            continue;
        }
        // Strip trailing newline.
        line[strcspn(line, "\r\n")] = '\0';
        if (strcmp(line, "plant") == 0) {
            do_plant();
        } else if (strcmp(line, "scrub_on") == 0) {
            g_scrub_enabled = 1;
            printf("SCRUB_ON\n");
            fflush(stdout);
        } else if (strcmp(line, "scrub_off") == 0) {
            g_scrub_enabled = 0;
            printf("SCRUB_OFF\n");
            fflush(stdout);
        } else if (strcmp(line, "status") == 0) {
            do_status();
        } else if (strcmp(line, "selftest") == 0) {
            do_selftest();
        } else if (strcmp(line, "fault_abort") == 0) {
            printf("FAULTING via abort()...\n");
            fflush(stdout);
            vTaskDelay(50 / portTICK_PERIOD_MS);
            abort();
        } else if (strcmp(line, "fault_restart") == 0) {
            printf("FAULTING via esp_restart()...\n");
            fflush(stdout);
            vTaskDelay(50 / portTICK_PERIOD_MS);
            esp_restart();
        } else if (strcmp(line, "fault_wdt") == 0) {
            printf("FAULTING via INT-WDT spin (interrupts off)...\n");
            fflush(stdout);
            vTaskDelay(50 / portTICK_PERIOD_MS);
            portDISABLE_INTERRUPTS();
            while (1) {
                // Spin with interrupts off; INT WDT fires -> panic ->
                // __wrap_esp_restart_noos -> scrub -> reset.
            }
        } else if (strcmp(line, "fault_hpwdt") == 0) {
            printf("FAULTING via MWDT0 system reset (pure hardware)...\n");
            fflush(stdout);
            vTaskDelay(50 / portTICK_PERIOD_MS);
            // Arm Timer Group 0 WDT: stage0 -> system reset after ~1 s
            // (40 MHz / 40000 = 1 kHz ticks). Interrupts stay ON so the
            // INT WDT stays fed; MWDT0 is never fed. Neither the shutdown
            // handler (only esp_restart() calls those) nor the noos
            // wrapper (only the panic path calls that) can run: the reset
            // is pure hardware. Expect CANARY_REMANENT even with scrub on.
            //
            // HAL ordering trap: wdt_hal_init() RE-LOCKS write-protect on
            // exit, so the unlock must come AFTER init — anything configured
            // before the unlock is silently dropped and the WDT never fires.
            wdt_hal_context_t mwdt0;
            wdt_hal_init(&mwdt0, WDT_MWDT0, 40000, false);
            wdt_hal_write_protect_disable(&mwdt0);
            wdt_hal_config_stage(&mwdt0, WDT_STAGE0, 1000,
                                 WDT_STAGE_ACTION_RESET_SYSTEM);
            wdt_hal_enable(&mwdt0);
            wdt_hal_feed(&mwdt0);
            wdt_hal_write_protect_enable(&mwdt0);
            vTaskDelay(3000 / portTICK_PERIOD_MS);  // MWDT0 fires at ~1 s
            // Failsafe: still alive means the WDT never fired (misconfig).
            // Fall back to abort so the outcome (CLEARED via wrapper) is
            // visibly different from a true hardware reset (REMANENT).
            printf("HPWDT DID NOT FIRE (unexpected) — falling back to abort\n");
            fflush(stdout);
            vTaskDelay(50 / portTICK_PERIOD_MS);
            abort();
        } else if (line[0] != '\0') {
            printf("UNKNOWN '%s'\n", line);
            fflush(stdout);
        }
        printf("> ");
        fflush(stdout);
    }
}
