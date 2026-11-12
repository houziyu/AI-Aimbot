#include "xy_protocol.h"
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include "driver/uart.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static atomic_bool connected;
static uint32_t session;
static uint32_t sequence;
static int64_t last_report_us;

static uint32_t clock_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

static uint16_t checksum(const char *text)
{
    uint16_t crc = 0xffff;
    while (*text) {
        crc ^= (uint16_t)(uint8_t)*text++ << 8;
        for (int bit = 0; bit < 8; bit++) {
            crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
        }
    }
    return crc;
}

static void reply(const char *body)
{
    printf("%s*%04X\n", body, checksum(body));
    fflush(stdout);
}

static void acknowledge(uint32_t seq, const char *status)
{
    char body[96];
    snprintf(body, sizeof(body), "A %"PRIu32" %"PRIu32" %"PRIu32" %d %s",
             session, seq, clock_ms(), atomic_load(&connected), status);
    reply(body);
}

void xy_set_connected(bool state)
{
    atomic_store(&connected, state);
}

static void process_line(char *line)
{
    char *separator = strrchr(line, '*');
    if (!separator || strlen(separator + 1) != 4) {
        return;
    }
    char *end;
    unsigned long received_crc = strtoul(separator + 1, &end, 16);
    if (*end) {
        return;
    }
    *separator = 0;
    if (received_crc != checksum(line)) {
        return;
    }
    uint32_t token, seq, deadline;
    int dx, dy, consumed = 0;
    char operation;
    if (sscanf(line, "H %"SCNu32"%n", &token, &consumed) == 1
            && consumed > 0 && !line[consumed] && token != 0) {
        session = token;
        sequence = 0;
        char body[96];
        snprintf(body, sizeof(body), "R 1 %"PRIu32" %"PRIu32" %d", session, clock_ms(), atomic_load(&connected));
        reply(body);
        return;
    }
    consumed = 0;
    int fields = sscanf(line, "%c %"SCNu32" %"SCNu32" %"SCNu32" %d %d%n",
                        &operation, &token, &seq, &deadline, &dx, &dy, &consumed);
    if (fields != 6 || consumed == 0 || line[consumed] || token != session || !session) {
        return;
    }
    if (operation != 'M' && operation != 'P' && operation != 'S') {
        return;
    }
    if ((int32_t)(seq - sequence) <= 0) {
        acknowledge(seq, "DUP");
        return;
    }
    sequence = seq;
    if (operation == 'S' || operation == 'P') {
        acknowledge(seq, "STATUS");
        return;
    }
    int32_t remaining = (int32_t)(deadline - clock_ms());
    if (remaining <= 0 || remaining > 200) {
        acknowledge(seq, "EXPIRED");
        return;
    }
    if (dx < -127 || dx > 127 || dy < -127 || dy > 127) {
        acknowledge(seq, "RANGE");
        return;
    }
    if (!atomic_load(&connected)) {
        acknowledge(seq, "BLE");
        return;
    }
    int64_t now = esp_timer_get_time();
    if (now - last_report_us < 8000) {
        acknowledge(seq, "BUSY");
        return;
    }
    esp_err_t result = xy_send_move((int8_t)dx, (int8_t)dy);
    if (result == ESP_OK) {
        last_report_us = now;
    }
    acknowledge(seq, result == ESP_OK ? "OK" : "SEND");
}

static void serial_task(void *unused)
{
    char line[128];
    size_t length = 0;
    bool overflow = false;
    uint8_t input[256];
    while (true) {
        int count = uart_read_bytes(UART_NUM_0, input, sizeof(input), pdMS_TO_TICKS(2));
        for (int i = 0; i < count; i++) {
            if (input[i] == '\n') {
                line[length] = 0;
                if (!overflow) {
                    process_line(line);
                }
                length = 0;
                overflow = false;
            } else if (input[i] != '\r') {
                if (length + 1 < sizeof(line)) {
                    line[length++] = (char)input[i];
                } else {
                    overflow = true;
                }
            }
        }
    }
}

void xy_protocol_start(void)
{
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 2048, 0, 0, NULL, 0));
    configASSERT(xTaskCreate(serial_task, "xy_uart", 4096, NULL, 5, NULL) == pdPASS);
}
