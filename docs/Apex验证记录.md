# Apex 图片与视频验证

日期：2026-11-13。代码优化与模型适配分开记录：五项工程优化已实现，现有通用人物模型在 Apex 交战画面上仍有未检出，不能以程序正常运行代替识别准确性验证。

## 样例与方法

- 8 张图片：Steam 商店 5 张官方宣传截图、3 张第一人称交战截图。
- 一段官方 **Apex Legends: Cipher Gameplay Trailer WW** 视频，1920 × 1080、30 fps、约 94.6 秒；每个模型实际解码和处理 **2,837 帧**。视频混合了游戏镜头、特写、标题和片尾，并非一段连续实战录像。
- 比较仓库自带的 `yolov5s320Half.onnx` 与 `yolov5m320Half.onnx`，使用 DirectML，置信度 0.40、默认人物类别 0。
- 图片分别检查整图缩放与原始分辨率的中心 320 × 320 区域；视频按原始分辨率中心 320 × 320 区域逐帧检查，与当前桌面默认截图范围一致。
- 视频使用源帧时间推进目标保持逻辑，明显转场重置跟踪。推理、解码、NMS 和目标筛选均为真实代码；没有打开串口、运行 Apex 客户端或发送鼠标位移。
- 没有逐帧人工真值标注，因此下面的“有检测帧数”不是准确率、召回率或敌人识别率。多人交叉的身份保持由合成序列回归测试覆盖，本视频不用于宣称身份跟踪准确率。

## 视频结果

| 模型 | 已处理帧 | 有检测结果的帧 | 选出目标的帧 | 检测与筛选 P50 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| YOLOv5s | 2,837 | 463 | 442 | 8.37 ms | 9.24 ms |
| YOLOv5m | 2,837 | 517 | 498 | 13.45 ms | 14.38 ms |

较大模型检出的帧数更多，但这些结果未经全量真值核对，不能推导为“准确率更高”。特写中中心裁剪只包含脸、手臂或胸部时，模型有未检出现象；目标位于中心裁剪区域外时，不检测属于当前截图范围的预期行为。

## 图片结果与人工查看

下表记录检测框数量，按「整图 / 中心裁剪」排列；不是人工标注的人数。

| 样例 | s 模型 | m 模型 | 查看结论 |
| --- | --- | --- | --- |
| 官方截图 0 | 3 / 1 | 2 / 1 | 可检测部分完整人物；中心裁剪改变了可见身体范围 |
| 官方截图 1 | 1 / 0 | 1 / 0 | 完整人物可检出，中心局部特写未检出 |
| 官方截图 2 | 0 / 1 | 1 / 1 | 整图缩小会损失小人物细节，中心裁剪可检出局部目标 |
| 官方截图 3 | 2 / 0 | 2 / 0 | 作为不同构图的补充样例，不能替代实战截图 |
| 官方截图 4 | 1 / 0 | 1 / 0 | 作为不同构图的补充样例，不能替代实战截图 |
| 走廊开镜交战 | 0 / 0 | 0 / 0 | 镜内目标与枪口、光效、遮挡混在一起，两模型均未检出 |
| Kings Canyon 开镜交战 | 1 / 0 | 0 / 0 | s 的整图检测框位于右侧背景，未落在镜内交战目标上；中心两模型均未检出 |
| 倍镜交战 | 0 / 0 | 0 / 0 | 镜内存在命中特效、数字及遮挡，两模型均未检出 |

人工检查了原图及检测框对照图。3 张第一人称交战图在默认中心裁剪下均无检测结果；这一小批样例说明模型适配仍需改进，但不代表所有 Apex 场景的总体表现。当前模型只识别人形，不能区分敌我、幻象或倒地状态。

没有因这次少量样例自动切换模型、下调置信度或改写用户配置。进一步提升 Apex 识别需要有代表性的实战样本与人工标注，用独立样本集评估漏检、误检和跨帧稳定性。

## 来源

| 素材 | 原始页面 |
| --- | --- |
| 5 张官方截图与 Cipher 视频 | [Apex Legends Steam 商店](https://store.steampowered.com/app/1172470/Apex_Legends/) |
| 走廊开镜交战图 | [たまえーけー：エイム＋遮蔽物](https://note.com/aktamax/n/nb88716b87775) |
| Kings Canyon 开镜交战图 | [Red Bull：Apex Legends landing locations](https://www.redbull.com/gb-en/apex-legends-best-places-to-land) |
| 倍镜交战图 | [GamePro：Apex Legends PC screenshots](https://www.gamepro.de/galerien/apex_legends%2C133900.html) |

下载地址与 SHA256 在 `tests/fixtures/apex-sources.json`。媒体版权属于原权利人，仅下载到本机离线分析，未把原始图片或视频加入仓库。另检索到的 Steam 社区热门图片多为插画、商店或结算画面，已排除在这 8 张测试样例之外。

## 复现与输出

在项目目录运行：

```powershell
.\.venv\Scripts\python.exe tools/fetch_apex_samples.py --video
.\.venv\Scripts\python.exe tools/check_media.py artifacts/apex-validation/cipher-gameplay-1080p.mp4 --provider DmlExecutionProvider --output artifacts/apex-validation/yolov5s
.\.venv\Scripts\python.exe tools/check_media.py artifacts/apex-validation/cipher-gameplay-1080p.mp4 --model yolov5m320Half.onnx --provider DmlExecutionProvider --output artifacts/apex-validation/yolov5m
.\.venv\Scripts\python.exe tools/check_media.py artifacts/apex-validation/combat-corridor.png artifacts/apex-validation/combat-kings-canyon.jpg artifacts/apex-validation/combat-scope.jpg --provider DmlExecutionProvider --output artifacts/apex-validation/combat-s
```

未安装 DirectML 时将 `--provider` 换为 `CPUExecutionProvider`。`check_media.py` 也支持其他本地图片和视频；每个输出目录生成 `report.json`、逐帧坐标/置信度/时间的 `*-frames.json` 和标注对照图 `*-sheet-*.jpg`。重新运行会更新同名输出。

`benchmark_backends.py` 可比较同一静态输入下的后端速度与输出一致性，`check_pipeline.py --provider DmlExecutionProvider --simulate-focus` 可检查真实截图与模拟串口链路；两者与视频逐帧测量的统计范围不同。
