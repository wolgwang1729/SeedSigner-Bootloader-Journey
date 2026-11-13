idf_component_register(SRCS "hello_sram.c"
                        REQUIRES stateless_shim
                        PRIV_REQUIRES spi_flash esp_timer hal soc
                        INCLUDE_DIRS "")
