/*
 * Stateless PSRAM shim for Kern (ESP32-P4, ESP-IDF v6.1)
 *
 * Adapted from the SeedSigner P4 MicroPython shim. The loader has already
 * initialized PSRAM, clocks, cache/MMU and UART, verified the signed bundle,
 * mapped the payload's PSRAM segments, and disabled the watchdogs. A normal
 * ESP-IDF `call_start_cpu0()` would repeat that hardware init and reset the
 * loader's state, so this shim replaces it:
 *
 *   my_entry_point  - naked trampoline: FPU, gp, dedicated stack
 *   __wrap_call_start_cpu0 - software-only IDF startup:
 *       clear BSS, install vectors, clocks, MMU software context,
 *       run ESP_SYSTEM_INIT_FN stage 0, constructors, stage 1,
 *       add the post-image PSRAM window to the heap, start the app.
 *
 * The app links with:
 *   -Wl,-e,my_entry_point
 *   -Wl,--wrap=call_start_cpu0
 * plus wraps for the hardware-init functions that the loader already ran.
 *
 * IDF v6.1 notes:
 *   - the init-function array is `_esp_sys_init_fn_start/end`
 *   - constructors are run with `__libc_init_array()` (same as IDF's
 *     start_cpu0_default), not the old __init_priority_array symbols
 *   - build the payload with CONFIG_FREERTOS_UNICORE=y and
 *     CONFIG_ESP_SYSTEM_SINGLE_CORE_MODE=y, matching the loader's CPU0-only
 *     handoff.
 */

#include <stdint.h>
#include <string.h>
#include <stdarg.h>

#include "esp_attr.h"
#include "esp_err.h"
#include "esp_rom_sys.h"
#include "esp_heap_caps.h"
#include "esp_cpu.h"
#include "hal/wdt_hal.h"
#include "soc/soc.h"
#include "soc/timer_group_struct.h"
#include "hal/interrupt_clic_ll.h"
#include "soc/interrupts.h"

/* The loader owns UART0; give the ROM FIFO a moment to drain before the next
 * stage. The SeedSigner shim used a 5,000,000-iteration busy loop; this is a
 * real delay that is also tolerable in esp-emu. */
static void shim_uart_drain(void)
{
    esp_rom_delay_us(2000);
}

__attribute__((used, section(".data"), aligned(16)))
uint8_t custom_boot_stack[8192] = { 0 };

void IRAM_ATTR __attribute__((naked)) my_entry_point(void)
{
    asm volatile (
        "li   t0, 0x6000            \n"
        "csrs mstatus, t0           \n"
        ".option push                \n"
        ".option norelax             \n"
        "la   gp, __global_pointer$  \n"
        ".option pop                 \n"
        "la   sp, custom_boot_stack  \n"
        "li   t0, 8192               \n"
        "add  sp, sp, t0             \n"
        "tail __wrap_call_start_cpu0 \n"
    );
}

extern void __real_call_start_cpu0(void);
extern int Cache_Invalidate_All(uint32_t map);

void IRAM_ATTR my_trap_handler(void)
{
    uint32_t mcause, mepc;
    asm volatile ("csrr %0, mcause" : "=r"(mcause));
    asm volatile ("csrr %0, mepc" : "=r"(mepc));
    esp_rom_printf("\r\nSHIM TRAP! mcause=0x%08x mepc=0x%08x\r\n", mcause, mepc);
    shim_uart_drain();
    while (1) {
    }
}

/* IDF v6.1 startup array type. Keep this local so the shim does not depend on
 * a private esp_system header. */
typedef struct {
    esp_err_t (*fn)(void);
    uint16_t cores;
    uint16_t stage;
} esp_system_init_fn_t;

extern esp_system_init_fn_t _esp_sys_init_fn_start;
extern esp_system_init_fn_t _esp_sys_init_fn_end;

extern void esp_startup_start_app(void);
extern void esp_clk_init(void);
extern void esp_perip_clk_init(void);
extern void esp_mmu_map_init(void);

static void core_intr_matrix_clear(void)
{
    for (int i = 0; i < ETS_MAX_INTR_SOURCE; i++) {
        interrupt_clic_ll_route(0, i, 0);
    }
}

extern int _bss_start_low, _bss_start_high;
extern int _bss_end_low, _bss_end_high;
extern int _rtc_bss_start, _rtc_bss_end;
extern int _iram_bss_start, _iram_bss_end;

void IRAM_ATTR __attribute__((noinline)) __wrap_call_start_cpu0(void)
{
    esp_rom_printf("\r\n[KERN-SHIM] __wrap_call_start_cpu0 entered\r\n");

    /* The loader already disabled these, but the payload's reset state can
     * differ after the jump; make it explicit and idempotent. */
    wdt_hal_context_t rwdt_ctx = RWDT_HAL_CONTEXT_DEFAULT();
    wdt_hal_write_protect_disable(&rwdt_ctx);
    wdt_hal_disable(&rwdt_ctx);
    wdt_hal_write_protect_enable(&rwdt_ctx);

    REG_WRITE(0x50116020, 0x50D83AA1);
    REG_WRITE(0x5011601C, (1U << 31) | (1U << 30) | (1U << 19) | (1U << 18));
    REG_WRITE(0x50116020, 0);

    REG_WRITE(0x50116018, 0x50D83AA1);
    REG_WRITE(0x50116014, (1U << 31));
    REG_CLR_BIT(0x50116000, (1U << 31) | (0xFFFU << 19) | (1U << 12));
    REG_WRITE(0x5011602C, 0);
    REG_WRITE(0x50116030, 0xFFFFFFFF);
    REG_WRITE(0x50116018, 0);

    wdt_hal_context_t mwdt0_ctx = { .inst = WDT_MWDT0, .mwdt_dev = &TIMERG0 };
    wdt_hal_write_protect_disable(&mwdt0_ctx);
    wdt_hal_disable(&mwdt0_ctx);
    wdt_hal_write_protect_enable(&mwdt0_ctx);

    wdt_hal_context_t mwdt1_ctx = { .inst = WDT_MWDT1, .mwdt_dev = &TIMERG1 };
    wdt_hal_write_protect_disable(&mwdt1_ctx);
    wdt_hal_disable(&mwdt1_ctx);
    wdt_hal_write_protect_enable(&mwdt1_ctx);

    /* `call_start_cpu0` normally does this. The loader cannot leave the
     * payload's BSS in a known state because its own `.data` overlaps. */
    memset(&_bss_start_low, 0,
           ((uint8_t *)&_bss_end_low - (uint8_t *)&_bss_start_low));
    memset(&_bss_start_high, 0,
           ((uint8_t *)&_bss_end_high - (uint8_t *)&_bss_start_high));
    memset(&_rtc_bss_start, 0,
           ((uint8_t *)&_rtc_bss_end - (uint8_t *)&_rtc_bss_start));
    memset(&_iram_bss_start, 0,
           ((uint8_t *)&_iram_bss_end - (uint8_t *)&_iram_bss_start));
    esp_rom_printf("[KERN-SHIM] BSS cleared\r\n");

    asm volatile ("csrw mtvec, %0" : : "r"(my_trap_handler));
    Cache_Invalidate_All(0x03);
    asm volatile ("fence.i\n");

    esp_rom_printf("[KERN-SHIM] clocks init\r\n");
    esp_clk_init();
    esp_perip_clk_init();
    core_intr_matrix_clear();

    esp_rom_printf("[KERN-SHIM] esp_mmu_map_init\r\n");
    esp_mmu_map_init();

    esp_system_init_fn_t *p = &_esp_sys_init_fn_start;

    /* Stage 0: core init functions. The loader has already done the hardware
     * parts; the wraps below turn those individual calls into no-ops. */
    while (p < &_esp_sys_init_fn_end) {
        if ((p->cores & 1) && (p->stage == 0)) {
            esp_rom_printf("[KERN-SHIM] init stage0 %p\r\n", p->fn);
            shim_uart_drain();
            esp_err_t err = p->fn();
            if (err != ESP_OK) {
                esp_rom_printf("[KERN-SHIM] stage0 failed 0x%x\r\n", err);
                while (1) {
                }
            }
        }
        p++;
    }

    /* IDF's start_cpu0_default uses __libc_init_array(); use the same path
     * instead of the IDF 5.x __init_priority_array symbols. */
    esp_rom_printf("[KERN-SHIM] constructors\r\n");
    extern void __libc_init_array(void);
    __libc_init_array();

    /* Stage 1: secondary init functions assigned to CPU0. */
    p = &_esp_sys_init_fn_start;
    while (p < &_esp_sys_init_fn_end) {
        if ((p->cores & 1) && (p->stage == 1)) {
            esp_rom_printf("[KERN-SHIM] init stage1 %p\r\n", p->fn);
            shim_uart_drain();
            esp_err_t err = p->fn();
            if (err != ESP_OK) {
                esp_rom_printf("[KERN-SHIM] stage1 failed 0x%x\r\n", err);
                while (1) {
                }
            }
        }
        p++;
    }

    /* The loader staged the image into the first 8 MB of PSRAM. Expose the
     * rest to the payload heap. (Kern's normal esp_psram_init() is bypassed
     * because the loader owns the PSRAM MMU.) */
    esp_rom_printf("[KERN-SHIM] adding PSRAM heap\r\n");
    extern esp_err_t heap_caps_add_region_with_caps(const uint32_t caps[],
                                                    intptr_t start,
                                                    intptr_t end);
    uint32_t byte_aligned_caps[] = {
        MALLOC_CAP_SPIRAM | MALLOC_CAP_DEFAULT, 0,
        MALLOC_CAP_8BIT | MALLOC_CAP_32BIT | MALLOC_CAP_SIMD
    };
    heap_caps_add_region_with_caps(byte_aligned_caps, 0x48800000, 0x4A000000);

    /* CLIC vector tables: a normal IDF app gets these from init_cpu(); the
     * shim replaces call_start_cpu0(), so install them before the scheduler
     * starts or the tick/IWDT never feeds. */
    extern char _vector_table[];
    extern char _mtvt_table[];
    esp_cpu_intr_set_ivt_addr(_vector_table);
    esp_cpu_intr_set_mtvt_addr(_mtvt_table);

    esp_rom_printf("[KERN-SHIM] jumping to esp_startup_start_app\r\n");
    shim_uart_drain();
    esp_startup_start_app();

    while (1) {
    }
}

/* Hardware initialization that the loader already performed. */
void IRAM_ATTR __wrap_cache_hal_init(void)
{
    esp_rom_printf("[KERN-SHIM] skip cache_hal_init\r\n");
}

void IRAM_ATTR __wrap_mspi_timing_flash_tuning(void)
{
    esp_rom_printf("[KERN-SHIM] skip mspi_timing_flash_tuning\r\n");
}

int IRAM_ATTR __wrap_esp_psram_chip_init(void)
{
    esp_rom_printf("[KERN-SHIM] skip esp_psram_chip_init\r\n");
    return 0;
}

void IRAM_ATTR __wrap_bootloader_flash_update_id(void)
{
    esp_rom_printf("[KERN-SHIM] skip bootloader_flash_update_id\r\n");
}

int IRAM_ATTR __wrap_image_process(void)
{
    esp_rom_printf("[KERN-SHIM] skip image_process\r\n");
    return 0;
}

extern esp_err_t __real_spi_flash_init_chip_state(void);
extern void __real_esp_mspi_pin_init(void);
extern void __real_esp_mspi_pin_reserve(void);

esp_err_t IRAM_ATTR __wrap_spi_flash_init_chip_state(void)
{
    esp_rom_printf("[KERN-SHIM] spi_flash_init_chip_state -> real\r\n");
    return __real_spi_flash_init_chip_state();
}

void IRAM_ATTR __wrap_esp_mspi_pin_init(void)
{
    esp_rom_printf("[KERN-SHIM] esp_mspi_pin_init -> real\r\n");
    __real_esp_mspi_pin_init();
}

void IRAM_ATTR __wrap_esp_mspi_pin_reserve(void)
{
    esp_rom_printf("[KERN-SHIM] esp_mspi_pin_reserve -> real\r\n");
    __real_esp_mspi_pin_reserve();
}

void IRAM_ATTR __wrap_esp_rom_output_tx_wait_idle(uint8_t uart_no)
{
    (void)uart_no;
}

void IRAM_ATTR __wrap_esp_rom_uart_set_clock_baudrate(uint8_t uart_no,
                                                      uint32_t clock_hz,
                                                      uint32_t baud_rate)
{
    (void)uart_no;
    (void)clock_hz;
    (void)baud_rate;
}

void IRAM_ATTR __wrap_esp_rtc_init(void)
{
    esp_rom_printf("[KERN-SHIM] skip esp_rtc_init\r\n");
}
