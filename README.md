# 准星助手 · ESP32 桌面版

基于现有 AI-Aimbot 新增的 Windows 桌面程序，按照提供的「准星助手」UI 原型实现控制台、参数设置和运行记录。通过目标窗口截图进行 YOLOv5 ONNX 人物检测，再通过 ESP32 蓝牙鼠标串口协议发送双轴修正指令。

**桌面入口：`main_ui.py`，双击入口：`start_ui.bat`。** 项目已精简为桌面版，旧命令行入口、训练/导出代码和无关示例已移除。参数统一通过界面设置。

## 已实现功能

- 真实串口扫描、连接/断开、目标窗口选择。
- 独立「仅识别预览」：无需 ESP32，选择窗口即可验证截图和模型，不发送位移。
- 右键和 Caps Lock 快捷键可独立关闭；默认右键关闭、Caps Lock 开启，F8 随时关闭辅助。
- 目标窗口客户区中心截图，支持窗口移动、截图尺寸调整和底部遮罩。
- ONNX FP16/FP32 输入适配、RGB 预处理、等比例缩放补边、人物筛选和 NMS。
- 人物框与选取圆相交时可参与选择，结合框大小、短时运动方向及重叠保持目标；更近目标需持续占优才切换，漏检期间不输出。支持瞄准高度、死区、移动倍率与修正上限。
- 30 / 60 / 120 次每秒识别上限，可选 CPU 推理线程数。识别与设备通信分别运行，位移发送上限独立可调为 30–60 条每秒，默认 60。只发送最新结果，每帧最多发送一次，XY1 固件沿用画面剩余有效期（默认从截图开始计 100 ms）。
- 真实截图预览、检测框和瞄准点。性能监测显示识别/串口写入频率、各阶段耗时、最近 120 帧耗时中位数/P95，并分别统计串口写入、固件接受、拒绝及回执超时。
- XY1 以 60 次/秒的倍率为基准，按实际发送间隔换算位移；受单条修正上限约束，停顿、切换目标或进入死区后不积攒补发位移。旧版固定方向协议保留原行为。
- 界面普通数据最多每秒刷新 10 次，仅更新变化内容；快捷键仍每 20 ms 检查，P50/P95 在状态锁外最多每秒汇总 5 次。
- F8 立即关闭并作废待发结果，设备线程随后清理串口缓冲。窗口不在前台时暂停截图和输出。
- 分级恢复：窗口尺寸或位置暂时不合适时暂停等待；窗口关闭、截图或模型失败时停止识别并保留设备；串口异常时释放串口。蓝牙断开保留串口，恢复后需手动开启辅助。
- 多套参数方案、复制当前参数、载入默认参数、撤销本次程序会话中的上一次应用；支持可选状态提示音，默认关闭。
- 本地配置持久化、明确的运行/暂停/错误状态、最近 200 条事件和轮转日志。

## 快速安装

环境：Windows 10/11、64 位 Python。当前开发验证使用 Python 3.13；先用 CPU 完成配置，再考虑 GPU。

在项目目录打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main_ui.py
```

安装完成后可以双击 `start_ui.bat`。无需激活虚拟环境，也无需安装 Torch 或 CUDA；`requirements.txt` 是唯一的运行依赖清单。

仓库自带 `yolov5s320Half.onnx`（默认）及较大的 `yolov5m320Half.onnx`，可以在参数设置中选择。

## 第一次使用

还没连接设备时，可以先选择目标窗口，点击 **仅识别预览**，再切回目标窗口。这个模式只检查识别效果；停止预览后再开启辅助。F8 可以停止辅助或预览，预览期间右键/Caps Lock 不会开启位移输出。

1. 将当前已能控制光标的 ESP32 接到电脑，在 Windows 蓝牙设置中确认已连接 `ESP Mouse`。
2. 关闭 IDF Monitor、Arduino Serial Monitor、旧版辅助等占用串口的程序。
3. 打开桌面版，刷新串口，选择对应 COM 口并点击 **连接设备**。
4. 打开需要识别的窗口，点击 **刷新窗口**，选择该窗口。开始时可用显示人物图片的测试窗口验证检测。
5. 参数保持默认：CPU、320 截图、置信度 0.40、倍率 0.40、死区 12。
6. 点击 **开启辅助**，切回目标窗口。或切回目标窗口后按 Caps Lock 开启。
7. 再按 Caps Lock 关闭；**F8 始终只关闭**。回到助手前台会暂停截图与输出，保留开启状态。

「参数设置 → 辅助快捷键」可以分别启用或关闭鼠标右键、Caps Lock，点击「保存并应用」后生效。默认关闭右键快捷键，避免换弹后再次开镜时切换辅助。旧配置缺少快捷键字段时也采用此默认值。

助手自身窗口处于前台时，右键和 Caps Lock 不切换辅助，避免编辑参数时误触；请使用界面按钮。快捷键不拦截原始输入，右键仍传给目标程序，Caps Lock 仍改变系统大小写状态。

完整操作、调参和排错见 **[使用教程](docs/使用教程.md)**。

![桌面控制台](docs/ui-console.png)

## 当前硬件协议与限制

```text
Windows 截图 → ONNX 检测 → 目标选择 → USB 串口（115200）
    → ESP32 收到 XY 双轴位移 → 蓝牙 HID → Windows 鼠标
```

| 字节 | 方向 |
| --- | --- |
| `w` | 向上 |
| `a` | 向左 |
| `s` | 向下 |
| `d` | 向右 |

连接时自动识别 XY1 双轴固件，界面显示「XY 双轴可变位移」及蓝牙连接状态。每条指令包含 X、Y 相对位移，各为 -127 到 127 counts；倍率和修正上限作用于实际发送的位移，支持 1 count 小步修正。上表为旧版方向固件的兼容协议，旧固件每次沿一个轴移动固定 10 counts。

XY1 包含版本握手、CRC16、会话标识、序号、状态查询和截止时间。电脑侧同一时刻只保留一条待回执的移动，在 250 ms 内未处理到有效回执便停止并断开串口。固件接受表示报告已交给蓝牙栈，Windows 实际接收延迟需另外测量。旧固件的蓝牙状态需在 Windows 中确认。

固件源码、构建、协议和备份恢复说明见 [ESP32-S3 XY 固件](firmware/esp32_xy/README.md)。USB HID 选项需要对应固件。

## 配置与目录

配置：`%LOCALAPPDATA%\AimAssist\settings.json`；参数方案：同目录 `profiles.json`；日志：同目录 `runtime.log`，最多保留 2 个历史文件，每个约 1 MB。旧配置自动补齐新增字段的默认值。重启后辅助与预览始终关闭，不自动连接设备；窗口句柄不持久化，需重新选择。

参数方案保存当前表单，载入方案和默认参数后需点击「保存并应用」；同名方案会覆盖，复制会生成新名称。方案不绑定串口或窗口。撤销恢复并保存本次会话中上一次应用前的参数。

```text
main_ui.py             桌面启动入口
start_ui.bat           Windows 双击启动
requirements.txt       运行依赖
aim_assist/
  ui.py                原生 PySide6 三页界面
  runtime.py           独立识别/设备线程、结果有效期、状态与取消控制
  vision.py            ONNX 推理、NMS、目标选择
  movement.py          XY1 位移时间归一化与上限控制
  benchmark.py         CPU/GPU 离线测速与输出一致性比较
  windows.py           窗口枚举、客户区坐标、前台判断
  settings.py          配置校验与原子保存
  profiles.py          多套参数方案与原子保存
esp32_ble_mouse.py     现有固件协议和方向测试 CLI
tests/                 算法、协议、后台状态回归测试
tests/fixtures/        截图联调使用的样例图片
tools/check_ui.py      不连接硬件的界面渲染检查
tools/check_pipeline.py 真实截图与模型的模拟串口联调
tools/benchmark_backends.py CPU/GPU 可重复测速与 JSON 报告
tools/check_media.py    本地截图/视频逐帧识别检查（无串口）
tools/fetch_apex_samples.py 获取记录来源及校验值的 Apex 公开样例
docs/使用教程.md        安装、操作、调参、排错
```

## 开发验证

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe tools/check_ui.py
.\.venv\Scripts\python.exe tools/check_pipeline.py --simulate-focus
.\.venv\Scripts\python.exe tools/check_pipeline.py --simulate-focus --preview-only
.\.venv\Scripts\python.exe tools/check_pipeline.py --simulate-focus --protocol legacy
.\.venv\Scripts\python.exe tools/check_pipeline.py --simulate-focus --provider DmlExecutionProvider --rate 120
.\.venv\Scripts\python.exe tools/benchmark_backends.py --output artifacts/backend-benchmark.json
```

测试使用模拟串口与截图，不移动真实光标；界面检查生成 `artifacts/` 图片。真实设备、蓝牙链路和目标程序中的最终手感仍需要硬件联调。模型仅按类别 0 识别人形，不能区分敌我、阵营或遮挡关系。

实际执行记录及检查边界见 [开发验证记录](docs/验证记录.md)。

Apex 专项已用 8 张公开截图及一段 1080p 视频检查两套自带模型。代码链路通过不等于人物检测适合 Apex：开镜交战截图仍有漏检，详见 [Apex 验证记录与来源](docs/Apex验证记录.md)。

## 技术资料与原项目

- [ONNX Runtime Python API](https://onnxruntime.ai/docs/api/python/api_summary.html)
- [Qt 线程与对象](https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-threads-qobject.html)
- [MSS 截图示例](https://python-mss.readthedocs.io/stable/examples.html)
- 基于 RootKit-Org/AI-Aimbot 开发；原项目授权见 [LICENSE](LICENSE)。旧版实现可通过 Git 历史查看。
