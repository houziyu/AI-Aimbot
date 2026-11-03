# AI-Aimbot：基于 YOLOv5 的屏幕视觉识别与辅助控制

> [!IMPORTANT]
> 原项目 RootKit 已停止维护，不再提供安装指导或故障支持。本分支包含后续的兼容性修复与运行流程优化，相关用法以本文及当前代码为准。

项目通过截取指定窗口中心区域，使用 YOLOv5 检测人物，再根据配置进行目标选择、可视化和鼠标辅助控制。原作者将其定位为教育与研究项目，使用时请遵守相关游戏与平台的规则。

## 运行方式

三个入口共用同一套图像处理、目标选择、预览与资源清理流程，主要区别在于推理后端。实际速度取决于硬件、模型和运行环境。

| 入口 | 推理后端 | 适用环境 |
| --- | --- | --- |
| `main.py` | PyTorch | 有可用 CUDA 时使用 NVIDIA GPU，否则使用 CPU |
| `main_onnx.py` | ONNX Runtime | 通过配置选择 CPU、DirectML 或 CUDA |
| `main_tensorrt.py` | TensorRT 8 | NVIDIA CUDA GPU，以及与环境匹配的 TensorRT 引擎 |

截图与输入控制依赖 Windows API，因此根目录的三个入口面向 Windows 环境。共用运行流程不需要 CuPy。

## 安装

### 1. 创建 Python 环境

本地验证使用 Python 3.13；对应依赖版本记录在 `constraints-py313.txt`。TensorRT 不属于这套验证环境，需要单独准备与其绑定兼容的 Python、CUDA 和 TensorRT 环境。

在项目根目录打开 PowerShell：

~~~powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
~~~

如果 PowerShell 无法执行激活脚本，可以用 `.\venv\Scripts\python.exe` 代替下文命令中的 `python`，直接使用虚拟环境。

### 2. 安装 PyTorch

先安装所需的 PyTorch 构建，再安装项目依赖，以保留所选的 CPU 或 CUDA 版本。

NVIDIA GPU 的本地验证环境使用 CUDA 12.8 构建，以下为对应命令示例。其他环境应选择与驱动兼容的构建：

~~~powershell
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
~~~

使用 CPU，或仅通过 DirectML 运行 ONNX 时，可以安装 CPU 构建：

~~~powershell
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
~~~

### 3. 安装项目依赖

仅使用 PyTorch 入口：

~~~powershell
python -m pip install -r requirements.txt
~~~

使用本地验证过的 Python 3.13 依赖组合：

~~~powershell
python -m pip install -r requirements-py313.txt
~~~

`requirements-py313.txt` 会应用版本约束，并安装 DirectML 版 ONNX Runtime。安装它不会自动修改 `config.py`：运行 ONNX 时，默认的 `onnxChoice = 1` 仍表示使用 CPU；要使用 DirectML，需改为 `2`。

也可以根据需要单独选择 ONNX 环境：

| `onnxChoice` | 推理设备 | 安装命令 |
| --- | --- | --- |
| `1` | CPU | `python -m pip install -r requirements-onnx-cpu.txt` |
| `2` | 支持 DirectML 的 GPU | `python -m pip install -r requirements-onnx-directml.txt` |
| `3` | NVIDIA CUDA GPU | `python -m pip install -r requirements-onnx-cuda.txt` |

**一个虚拟环境只安装一种 ONNX Runtime 发行包。** CPU、DirectML、CUDA 发行包共享 `onnxruntime` 导入名称，请使用独立环境切换，避免混装。CUDA 版还需要匹配的 CUDA/cuDNN 运行环境。

程序导入模块时不会自动调用 pip 安装或升级依赖。缺少依赖时，应根据报错安装后重新启动。

## 启动与操作

在项目根目录运行对应入口，三者任选一个：

~~~powershell
# PyTorch
python main.py

# ONNX Runtime
python main_onnx.py

# TensorRT
python main_tensorrt.py
~~~

程序先显示实际使用的后端、设备或执行提供程序、输入尺寸及精度，并完成模型预热。随后列出可选择的窗口，输入编号即可。

- **Caps Lock**：按系统的 Caps Lock 开关状态启用或停用辅助控制。启动前可先将其关闭。
- **Q**：默认退出键，可通过 `aaQuitKey` 修改。
- **Ctrl+C**：在终端中中断运行。
- 启用预览后，预览窗口也使用配置的退出键。
- 选中窗口失去焦点、最小化，或截图区域超出所选显示输出时，截图和辅助控制暂停；满足条件后恢复。
- 在同一显示输出内移动窗口时，截图区域跟随窗口客户区中心更新。推理完成后也会再次检查窗口状态，避免对已移动或失焦的窗口执行旧结果。

正常退出、预览退出、中断及运行异常都会进入资源清理流程，释放截图设备并关闭预览窗口。

## 配置说明

配置集中在 `config.py`。以下为当前默认值。

### 图像与遮罩

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `screenShotWidth` | `320` | 窗口中心截图区域的宽度，单位为像素 |
| `screenShotHeight` | `320` | 窗口中心截图区域的高度，单位为像素 |
| `useMask` | `False` | 是否启用遮罩，遮罩区域不会送入有效图像内容 |
| `maskSide` | `"left"` | 遮罩位于左下角或右下角，可选 `"left"`、`"right"`，不区分大小写 |
| `maskWidth` | `80` | 遮罩宽度；启用遮罩时须大于 0，且不超过截图宽度 |
| `maskHeight` | `200` | 遮罩高度；启用遮罩时须大于 0，且不超过截图高度 |

截图的 BGRA/BGR 数据会统一转换为模型使用的 RGB 通道顺序；预览仍使用 BGR。遮罩和图像处理不会修改截图模块返回的原始数据。

### 检测与辅助控制

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `confidence` | `0.4` | 检测置信度阈值，范围为 0～1 |
| `iouThreshold` | `0.45` | NMS 重叠框抑制阈值，独立于置信度阈值，范围为 0～1 |
| `maxDetections` | `100` | 每帧最多保留的检测框数量 |
| `centerOfScreen` | `True` | 没有上一帧目标时，优先选择距截图中心最近的目标 |
| `aaMovementAmp` | `0.4` | 鼠标位移倍率，须为非负有限数值 |
| `headshot_mode` | `True` | 将控制点向检测框上方偏移；关闭后仍保留较小的向上偏移 |
| `aaQuitKey` | `"Q"` | 全局及预览退出键，支持一个 ASCII 字母或数字，不区分大小写 |

有上一帧目标时，会优先选择距其坐标最近的当前目标。没有检测结果、截图暂停或截图区域改变时，会清空上一帧目标。关闭 `centerOfScreen` 后，首次选择使用检测结果的原有顺序。

当前后处理按类别 `0` 筛选目标。使用自定义模型时，应确认类别映射与这项约定一致。

### 模型与推理后端

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `modelWeights` | `"yolov5s.pt"` | PyTorch 入口使用的权重文件；标准 YOLOv5 权重缺失时会尝试下载 |
| `onnxWeights` | `"yolov5s320Half.onnx"` | ONNX 入口使用的本地模型文件 |
| `tensorrtWeights` | `"yolov5s320Half.engine"` | TensorRT 入口使用的本地引擎文件 |
| `onnxChoice` | `1` | `1`：CPU；`2`：DirectML；`3`：CUDA，仅影响 ONNX 入口 |

相对模型路径以项目根目录为基准解析，不依赖启动命令所在的目录。

- PyTorch 截图尺寸必须是模型步长的整数倍。
- ONNX 会读取模型声明的输入名、数据类型和尺寸，支持浮点单精度与半精度输入。
- 本地默认 ONNX 模型的输入为 `[1, 3, 320, 320]`、`float16`。固定尺寸模型必须与配置的截图尺寸一致，修改截图尺寸前应检查模型。
- TensorRT 引擎的输入尺寸也会在启动时检查。
- 指定的 ONNX 执行提供程序不可用，或未实际启用时，程序会报错，不会静默切换到 CPU。

### 截图频率与缓冲区

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `captureFps` | `120` | 目标截图频率；实际频率受画面变化和运行环境影响 |
| `captureBuffer` | `4` | 循环截图缓冲区的容量，单位为帧，至少为 2 |
| `captureDevice` | `0` | BetterCam 截图适配器编号 |
| `captureOutput` | `None` | 显示输出编号，`None` 选择该适配器的主输出 |

**缓冲容量不等于截图频率。** `captureBuffer = 4` 表示最多容纳 4 帧，不代表每秒只截图 4 张；同样，原来的 512 帧缓冲也不代表每秒截图 512 张。

缓冲区循环覆盖旧帧，程序读取最新截图，不会等待缓冲区填满，也不会依次补算积压的旧帧。按默认 `320 × 320`、BGRA 每像素 4 字节计算：

| 缓冲容量 | 帧缓冲数据量 |
| --- | --- |
| 512 帧 | 约 200 MiB |
| 4 帧 | 约 1.56 MiB |

上述数值仅指帧缓冲数据，不包含模型、截图设备及其他运行内存。对当前读取最新帧的流程，较小缓冲主要减少内存占用，不能据此直接推算 FPS 提升。

共用流程只处理截图模块取得的变化帧，静止画面下 CPS 较低属于正常情况。将窗口移到其他显示器后，如果截图区域超出所选输出，会暂停；应将窗口移回，或退出后重新配置 `captureDevice` / `captureOutput`。

### 预览与性能统计

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `visuals` | `False` | 是否显示检测框预览 |
| `cpsDisplay` | `True` | 是否输出每秒完成的处理次数 |
| `performanceDisplay` | `False` | 是否输出各阶段的滚动平均耗时和 P95 耗时 |

开启 `performanceDisplay` 后，会输出截图、预处理、推理、后处理及完整单次循环的耗时。P95 表示样本中约 95% 的耗时不超过该值，可用于观察偶发卡顿。

CUDA 阶段计时会执行必要的设备同步，因此性能分析本身会增加开销。比较日常运行速度时，应保持相同的模型、截图尺寸、预览和统计配置。CPS 不是游戏 FPS，也不等同于单独的模型推理速度。

## TensorRT 环境与引擎导出

当前适配器使用 TensorRT 8 的绑定接口，需要可用的 CUDA GPU、本地 TensorRT 运行库及匹配的 Python 绑定。它不属于上面的 Python 3.13 验证环境，不能直接套用不同 Python、CUDA 或 TensorRT 版本的安装包。

仓库附带的 `.engine` 文件不保证适配所有设备和运行库。如果加载失败，应在目标环境中使用 `export.py` 重新导出。例如：

~~~powershell
python export.py --weights ./yolov5s.pt --include engine --half --imgsz 320 320 --device 0
~~~

该示例生成的文件名为 `yolov5s.engine`。导出完成后，在 `config.py` 中将 `tensorrtWeights` 改为该文件名，并保持截图尺寸与导出尺寸一致。

原项目的 TensorRT 教程使用 CUDA 11.8、TensorRT 8.6 与 Python 3.11 绑定，仅供对应旧环境参考，不代表当前所有环境都应安装这一组合。

## 项目结构

| 路径 | 用途 |
| --- | --- |
| `main.py`、`main_onnx.py`、`main_tensorrt.py` | 三个运行入口 |
| `app.py` | 共用主循环、输入控制、预览与退出清理 |
| `runtime.py` | 配置校验、颜色转换、检测框处理、目标选择及性能统计 |
| `inference.py` | PyTorch、ONNX 和 TensorRT 推理适配 |
| `gameSelection.py` | 窗口选择与截图会话，保留旧版三元组接口 |
| `config.py` | 用户配置 |
| `models/`、`utils/` | 随仓库提供的 YOLOv5 模型与工具代码 |
| `tests/` | 离线回归测试 |
| `customScripts/` | 社区独立脚本示例，不等同于根目录的共用运行流程 |
| `customModels/` | 社区模型说明与示例 |
| `Conda/` | 原项目的 Conda 安装资料 |

## 测试与验证范围

在项目根目录运行：

~~~powershell
python -m unittest discover -s tests -v
~~~

回归测试涵盖颜色通道、遮罩、像素坐标、跨帧目标选择、配置与模型元数据检查、推理提供程序检查、窗口移动与焦点变化、静态画面等待，以及异常退出清理。

本地已完成 PyTorch CPU/CUDA、ONNX CPU/DirectML 的离线模型推理验证，并验证了 CUDA 半精度非空检测结果的后处理。TensorRT 尚未在本地实测。

Windows 截图和输入控制的单元测试使用模拟对象，不会启动实际截图或移动鼠标。离线推理与回归测试不代表游戏实景中的识别精度、整体帧率或完整兼容性验证。

## 常见问题

**安装了 DirectML，运行 ONNX 仍然显示 CPU？**

检查 `config.py` 的 `onnxChoice` 是否为 `2`。安装依赖不会自动修改配置，启动时显示的执行提供程序才是实际选择结果。

**修改截图尺寸后无法启动？**

检查模型的固定输入尺寸。默认 ONNX 模型要求 `320 × 320`；PyTorch 要求尺寸为模型步长的整数倍；TensorRT 引擎也需要匹配的输入尺寸。

**为什么窗口切换后不再输出控制？**

共用流程只在所选窗口位于前台且截图区域有效时执行控制。切回该窗口、恢复窗口大小或将窗口移回所选显示输出后，会恢复处理。

**为什么画面不动时 CPS 下降？**

共用流程不重复推理未变化的截图。CPS 统计的是实际完成的处理次数，画面静止时不需要维持与目标截图频率相同的处理次数。

**缺少模型或依赖怎么办？**

按报错检查对应文件与依赖清单。标准 PyTorch 权重可以按原有下载逻辑获取；ONNX 模型与 TensorRT 引擎需要在配置路径下存在。依赖须自行安装，程序不会在导入阶段修改环境。

## 原项目资料与社区内容

以下资料来自原项目，可能与本分支的安装方式或代码结构不同：

- [基础代码包](https://github.com/RootKit-Org/AI-Aimbot-Starter-Code)
- [原入门视频（内容较旧）](https://www.youtube.com/watch?v=TCJHLbbeLhg)
- [原直播讲解（内容较旧）](https://www.youtube.com/watch?v=uniL5yR7y0M&ab_channel=RootKit)
- [原社区 Discord](https://discord.gg/rootkitorg)
- [YOLOv5 v7.0 权重发布页](https://github.com/ultralytics/yolov5/releases/tag/v7.0)

自定义脚本和模型可以分别参考 `customScripts/`、`customModels/` 中的示例。原项目已停止提供支持，历史视频和社区链接不表示仍有维护或答疑承诺。

## 许可证

项目许可证见 [LICENSE](LICENSE)；随仓库提供的 YOLOv5 代码文件包含相应的许可证声明。
