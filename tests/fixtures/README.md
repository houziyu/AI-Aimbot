# 截图联调样例

`rust-validation.jpg` 保留自本仓库原有的 `customModels/rust/val_batch1_labels.jpg`。

`tools/check_pipeline.py` 会显示其中的固定裁剪区域，用于验证真实窗口截图、模型推理、目标选择与模拟串口输出。该图片无需重新下载，不用于训练模型。

## Apex 公开样例

`apex-sources.json` 记录 8 张公开图片及一段官方视频的来源和 SHA256。运行 `tools/fetch_apex_samples.py --video` 获取到被 Git 忽略的 `artifacts/apex-validation/`，不在仓库内分发原始媒体。复现和模型局限见 `docs/Apex验证记录.md`。
