#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

void xy_protocol_start(void);
void xy_set_connected(bool connected);
esp_err_t xy_send_move(int8_t dx, int8_t dy);
