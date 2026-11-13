idf_component_register(SRCS "canary_scrub.c"
                        REQUIRES stateless_shim
                        PRIV_REQUIRES spi_flash esp_timer hal soc mbedtls
                        INCLUDE_DIRS "")

# Catch the panic path (abort/task-WDT go through esp_restart_noos, which
# skips shutdown handlers on IDF v5.5). The wrapper scrubs then calls real.
target_link_options(${COMPONENT_LIB} INTERFACE
    "-Wl,--wrap=esp_restart_noos"
)
