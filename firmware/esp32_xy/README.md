# ESP32-S3 XY 蓝牙鼠标固件

适配本机 ESP32-S3、16 MB Flash、CP2102N UART0，波特率 115200。蓝牙名称为 `ESP Mouse`，鼠标 HID 描述符沿用 Espressif 示例。一次报告包含有符号 X、Y 相对位移，范围各为 -127 到 127 counts，按钮和滚轮固定为零。

## 构建与烧录

在仓库根目录执行以下命令。

```powershell
.\.venv\Scripts\python.exe -m platformio run -d firmware/esp32_xy
.\.venv\Scripts\python.exe -m esptool --chip esp32s3 --port COM3 --baud 460800 write-flash 0x10000 firmware/esp32_xy/.pio/build/esp32s3/firmware.bin
```

此烧录命令适用于本次确认的分区布局，factory 位于 0x10000、大小 1 MB。项目的分区表记录了此布局。构建环境使用 PlatformIO espressif32 6.12.0 / ESP-IDF 5.5.0。

原始 16 MB 备份位于仓库 `artifacts/firmware-backup/esp32s3-original-20261112.bin`。SHA-256 为 `2df3c8c49de36bb8821bd5f9c1623496e5b12a571a4ad19778e84f0f213e2aa0`。本次部署只写应用分区，NVS 中的配对信息得以保留。完整恢复命令如下。

```powershell
.\.venv\Scripts\python.exe -m esptool --chip esp32s3 --port COM3 --baud 460800 write-flash 0 artifacts/firmware-backup/esp32s3-original-20261112.bin
```

## XY1 协议

每帧是 ASCII 正文、`*`、4 位大写十六进制 CRC16-CCITT、换行。CRC 初值 0xffff，多项式 0x1021，覆盖星号前的正文。下面展示正文，线上发送须带校验和。

| 方向 | 正文 | 含义 |
| --- | --- | --- |
| 主机 → 板 | `H token` | 新会话握手，token 为随机非零 uint32 |
| 板 → 主机 | `R 1 token clock connected` | 协议版本、板端毫秒时钟、加密蓝牙连接状态 |
| 主机 → 板 | `M token seq deadline dx dy` | 双轴移动，deadline 使用板端毫秒时钟 |
| 主机 → 板 | `P token seq deadline 0 0` | 状态查询 |
| 主机 → 板 | `S token seq deadline 0 0` | 停止标记，推进序号，后续重新采样 |
| 板 → 主机 | `A token seq clock connected status` | 指令处理回执 |

`status` 为 OK、STATUS、EXPIRED、BUSY、DUP、RANGE、BLE 或 SEND。OK 表示报告成功交给蓝牙栈。Windows 消费报告的时间需要另外测量。

上位机同一时刻只保留一条待回执的移动。回执超时 250 ms 会停止并断开串口，移动指令不会重试。目标消失时停止生成位移；停止或切换配置时发送 S，已交给蓝牙栈的报告仍可能到达 Windows。固件立即处理数据，没有持续移动任务；重复序号、过期位移、超范围位移均丢弃。移动有效期为约 80 ms，固件拒绝超过 200 ms 的未来截止时间。通过每次回执同步时钟，板端最短报告间隔为 8 ms。

主程序会自动握手识别 XY1，也兼容旧版 `w/a/s/d` 固件。新固件通过 `esp32_ble_mouse.py --port COM3` 测试，可输入 `5 -3` 验证双轴小步移动。

## 来源

`esp_hid_device_main.c`、`esp_hid_gap.c`、`esp_hid_gap.h` 和 `Kconfig.projbuild` 基于 Espressif ESP-IDF v5.5.4 的 esp_hid_device 示例，保留文件中的 Unlicense / CC0-1.0 声明。串口 XY1 协议及主机适配为本项目新增。

https://github.com/espressif/esp-idf/tree/v5.5.4/examples/bluetooth/esp_hid_device
