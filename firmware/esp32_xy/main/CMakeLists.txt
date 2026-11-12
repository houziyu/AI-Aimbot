idf_component_register(SRCS "esp_hid_device_main.c" "esp_hid_gap.c" "xy_protocol.c"
                       INCLUDE_DIRS "."
                       REQUIRES esp_hid
                       PRIV_REQUIRES nvs_flash esp_timer esp_driver_uart)
