idf_component_register(SRCS "stateless_hvfb_main.c" "hvfb_stateless.c"
                        REQUIRES stateless_shim
                        PRIV_REQUIRES esp_timer
                        INCLUDE_DIRS "")
