> [!CAUTION]
> # This tool is No Longer Supported by RootKit
> We will not offer help for issues that arise with this program, or assist in getting it running on your machine.
> You are free to fork and edit this tool yourself.

# 🎯 World's Best AI Aimbot 🎮

![World's Best AI Aimbot Banner](imgs/banner.png)

[![Pull Requests Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat)](https://makeapullrequest.com)


Want to make your own bot? Then use the [Starter Code Pack](https://github.com/RootKit-Org/AI-Aimbot-Starter-Code)!
--
--
## 🙌 Welcome Aboard!
We're a charity on a mission to educate and certify the upcoming wave of developers in the world of Computer Engineering 🌍. ~~Need assistance? Hop into our [Discord](https://discord.gg/rootkitorg) and toss your questions at `@Wonder` in the *#ai-aimbot channel* (be sure to stick to this channel or face the consequences! 😬). Type away your query and include `@Wonder` in there.~~

Our *AI Aimbot* 🤖 sharpshoots targets in **any game with humanoid characters**, harnessing the power of [YOLOv5](https://github.com/ultralytics). Currently, it's a ninja against anti-cheat systems, as it's visual-only. Still, watch out for manual player reports! 👀

Intended for educational use 🎓, our aim is to highlight the vulnerability of game devs to AI-driven cheats. Pass it along to your game developer buddies, and save their games from being outsmarted!

**⚠ Use at your own risk! If you're caught... well, you've been warned!**

## 📹 Instructional Media
- [Watch the tutorial video (Works But Outdated)](https://www.youtube.com/watch?v=TCJHLbbeLhg)
- [Watch the live stream explainer (Works But Outdated)](https://www.youtube.com/watch?v=uniL5yR7y0M&ab_channel=RootKit)
- [Join the Discord](https://discord.gg/rootkitorg)

## There are 3 Versions 🚀🚦🖥️
- Fast 🏃‍♂️ - `main.py` ✅ Easy to set up, Works on any computer 💻
- Faster 🏃‍♂️💨 - `main_onnx.py` ⚙️ May need to edit a file, Works on any computer 💻
- Fastest 🚀 - `main_tensorrt.py` 🏢 Enterprise level hard, Works on computers with Nvidia GPUs only 🎮

## 🧰 Requirements
- Nvidia RTX 980 🆙, higher or equivalent
- And one of the following:
  - Nvidia CUDA Toolkit 11.8 [DOWNLOAD HERE](https://developer.nvidia.com/cuda-11-8-0-download-archive)

## 🚀 Pre-setup Steps
1. Download and Unzip the AI Aimbot and stash the folder somewhere handy 🗂️.
2. Ensure you've got Python installed (like a pet python 🐍) – grab version 3.11 [HERE](https://www.python.org/downloads/release/python-3116/).
   - 🛑 Facing a `python is not recognized...` error? [WATCH THIS!](https://youtu.be/E2HvWhhAW0g)
   - 🛑 Is it a `pip is not recognized...` error? [WATCH THIS!](https://youtu.be/zWYvRS7DtOg)
3. Fire up `PowerShell` or `Command Prompt` on Windows 🔍.
4. To install `PyTorch`, select the appropriate command based on your GPU.
    - Nvidia `pip install torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118`
    - AMD or CPU `pip install torch torchvision torchaudio`
5. 📦 Run the command below to install the required Open Source packages:
```
pip install -r requirements.txt
```

### 🐍 Running on Python 3.13

The local Python 3.13 validation environment uses the package versions recorded in
`constraints-py313.txt`. Install PyTorch first, then install the DirectML environment below.
TensorRT is a separate optional installation; the bundled adapter requires TensorRT 8 and
an engine exported for the matching GPU/runtime. It is not part of the Python 3.13 validation set.

```powershell
# CUDA build (match the index to your driver; cu128 works for RTX 30xx/40xx)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements-py313.txt
```

Notes for 3.13 (and modern PyTorch/NumPy generally):

- `main.py` now loads `yolov5s.pt` through the bundled `models/` package instead of `torch.hub`.
  The weights download automatically on first run; set `modelWeights` in `config.py` to pick a size.
- `main_onnx.py` needs `onnxChoice = 2` (DirectML) or `3` (CUDA) to use your GPU.
- If you use `onnxChoice = 3`, install `requirements-onnx-cuda.txt` in a separate environment.
  Choose one ONNX Runtime distribution per environment; do not combine CPU, DirectML, and CUDA wheels.
  The shared runtime does not require CuPy.

## 🔌 How to Run (Fast 🏃‍♂️ Version)
Follow these steps **after** Python and all packages have been installed:

1. Open `PowerShell` ⚡ or `Command Prompt` 💻.
2. Input `cd `, then drag & drop the folder containing the bot code into the terminal.
3. Hit Enter ↩️.
4. Type `python main.py` and press Enter.
5. Use **CAPS_LOCK** to toggle the aimbot 🎯. It begins in the *off* state.
6. Pressing `q` 💣 at **ANY TIME** will shut down the program.

## 🔌 How to Run (Faster 🏃‍♂️💨 Version)
Follow these steps **after** Python and all packages have been installed:

1. Open the `config.py` 📄 file and tweak the `onnxChoice` variable to correspond with your hardware specs:
    - `onnxChoice = 1` # CPU ONLY 🖥
    - `onnxChoice = 2` # AMD/NVIDIA ONLY 🎮
    - `onnxChoice = 3` # NVIDIA ONLY 🏎️
2. Install the matching backend in your environment (choose one):
    ```
    # onnxChoice = 1
    python -m pip install -r requirements-onnx-cpu.txt
    # onnxChoice = 2
    python -m pip install -r requirements-onnx-directml.txt
    # onnxChoice = 3 (requires a compatible CUDA/cuDNN installation)
    python -m pip install -r requirements-onnx-cuda.txt
    ```
3. Follow the same steps as for the Fast 🏃‍♂️ Version above except for step 4, you will run `python main_onnx.py` instead.


## 🔌 How to Run (Fastest 🚀 Version)
Follow these sparkly steps to get your TensorRT ready for action! 🛠️✨

1. **Introduction** 🎬
   Watch the TensorRT section of the setup [video 🎥](https://www.youtube.com/watch?v=uniL5yR7y0M&ab_channel=RootKit) before you begin. It's loaded with useful tips!

2. **Oops! Don't Forget the Environment** 🌱
   We forgot to mention adding environmental variable paths in the video. Make sure to do this part!

3. **Get Support If You're Stumped** 🤔
   If you ever feel lost, you can always `@Wonder` your questions in our [Discord 💬](https://discord.gg/rootkitorg). Wonder is here to help!

4. **Use the shared runtime**
    The TensorRT entry point uploads RGB input directly with PyTorch. CuPy is not required.

5. **CUDNN Installation** 🧩
   Click to install [CUDNN 📥](https://developer.nvidia.com/downloads/compute/cudnn/secure/8.9.6/local_installers/11.x/cudnn-windows-x86_64-8.9.6.50_cuda11-archive.zip/). You'll need a Nvidia account to proceed. Don't worry it's free.

6. **Unzip and Relocate** 📁➡️
   Open the .zip CuDNN file and move all the folders/files to where the CUDA Toolkit is on your machine, usually at `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8`.

7. **Get TensorRT 8.6 GA** 🔽
   Fetch [`TensorRT 8.6 GA 🛒`](https://developer.nvidia.com/downloads/compute/machine-learning/tensorrt/secure/8.6.1/zip/TensorRT-8.6.1.6.Windows10.x86_64.cuda-11.8.zip).

8. **Unzip and Relocate** 📁➡️
   Open the .zip TensorRT file and move all the folders/files to where the CUDA Toolkit is on your machine, usually at `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8`.

9. **Python TensorRT Installation** 🎡
   Once you have all the files copied over, you should have a folder at `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\python`. If you do, good, then run the following command to install TensorRT in python.
   ```
   pip install "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\python\tensorrt-8.6.1-cp311-none-win_amd64.whl"
   ```
    🚨 If the following steps didn't work, don't stress out! 😅 The labeling of the files corresponds with the Python version you have installed on your machine. We're not looking for the 'lean' or 'dispatch' versions. 🔍 Just locate the correct file and replace the path with your new one. 🔄 You've got this! 💪

10. **Set Your Environmental Variables** 🌎
   Add these paths to your environment:
   - `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\lib`
   - `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\libnvvp`
   - `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin`

11. **Download Pre-trained Models** 🤖
   You can use one of the .engine models we supply. But if it doesn't work, then you will need to re-export it. Grab the `.pt` file here for the model you want. We recommend `yolov5s.py` or `yolov5m.py` [HERE 🔗](https://github.com/ultralytics/yolov5/releases/tag/v7.0).

12. **Run the Export Script** 🏃‍♂️💻
   Time to execute `export.py` with the following command. Patience is key; it might look frozen, but it's just concentrating hard! Can take up to 20 minutes.
   
   ```
   python .\export.py --weights ./yolov5s.pt --include engine --half --imgsz 320 320 --device 0
   ```
   
   Note: You can pick a different YOLOv5 model size. TensorRT's power allows for larger models if desired!

If you've followed these steps, you should be all set with TensorRT! ⚙️🚀


## ⚙️ Configurable Settings

*Default settings are generally great for most scenarios. Check out the comments in the code for more insights. 🔍 The configuration settings are now located in the `config.py` file!<br>
**CAPS_LOCK is the default for flipping the switch on the autoaim superpower! ⚙️ 🎯**

`useMask` - Set to `True` or `False` to turn on and off 🎭

`maskWidth` - The width of the mask to use. Only used when `useMask` is `True` 📐

`maskHeight` - The height of the mask to use. Only used when `useMask` is `True` 📐

`aaQuitKey` - The go-to key is `q`, but if it clashes with your game style, swap it out! ⌨️♻️

`headshot_mode` - Set to `False` if you're aiming to keep things less head-on and more centered. 🎯➡️👕

`cpsDisplay` - Toggle off with `False` if you prefer not to display the CPS in your command station. 💻🚫

`visuals` - Flip to `True` to witness the AI's vision! Great for sleuthing out any hiccups. 🕵️‍♂️✅

`aaMovementAmp` - The preset should be on point for 99% of players. Lower the digits for smoother targeting. Recommended doses: `0.5` - `2`. ⚖️🕹️

`confidence` - Stick with the script here unless you're the expert. 🧐✨

`screenShotHeight` - Same as above, no need for changes unless you've got a specific vision. 📏🖼️

`screenShotWidth` - Keep it constant as is, unless you've got reasons to adjust. 📐🖼️

`aaDetectionBox` - Default's your best bet, change only if you've got the know-how. 📦✅

`onnxChoice` - Gear up for the right graphics card—Nvidia, AMD, or CPU power! 💻👾

`centerOfScreen` - Keep this switched on to stay in the game's heart. ❤️🖥️

## 📊 Current Stats

The bot's efficiency depends on your setup. We achieved 100-150 CPS with our test specs below 🚀.

    - AMD Ryzen 7 2700
    - 64 GB DDR4
    - Nvidia RTX 3080

💡 Tip: Machine Learning can be tricky, so reboot if you keep hitting CUDA walls.

## 🤝 Community Based

We're all about collaboration. Your contributions can earn you credit and potential 💰!

**Want to volunteer? Have video or program ideas? Tell us!**

## ⚠️ Known Cheat-Detectable Games

Splitgate (reported by a Discord user 🕵️‍♂️), EQU8 detects win32 mouse movement library.

## 🚀 Custom Aimbots and Models

Show off your work or new models via Pull Requests in `customScripts` or `customModels` directories, respectively. Check out the `example-user` folder for guidance.

## 🌠 Future Ideas

 - [x] Mask Player to avoid false positives


Happy Coding and Aiming! 🎉👾


## Shared runtime and validation

The three root entry points share `app.py`, `runtime.py`, and `inference.py`. They use the same
RGB conversion, pixel coordinates, NMS thresholds, target selection, preview, and cleanup.
Community examples under `customScripts/` remain independent examples.

- Set `onnxWeights` / `tensorrtWeights` to change exported models. Relative model paths resolve
  from the project directory. ONNX reads the input name, precision, and shape from the model.
  A fixed-size model must match `screenShotWidth` / `screenShotHeight`; incompatible settings
  fail before capture starts. PyTorch image sizes must be multiples of the model stride.
- `confidence` controls detection confidence; `iouThreshold` separately controls NMS overlap.
  `maxDetections` caps the retained boxes. With no previous target, `centerOfScreen` prefers
  the closest target to the center; subsequent frames prefer the nearest previous coordinates.
  An empty frame, capture pause, or crop change resets the previous target.
- `captureBuffer = 4` uses about 1.6 MiB at 320 x 320 BGRA. `captureFps` caps acquisition.
  Only changed desktop frames are processed, so CPS can be lower on a static screen.
- Capture follows the selected window's client area. Minimizing it, switching focus, or moving
  the crop outside the selected output pauses capture and mouse control. Returning resumes it.
  `captureDevice` and `captureOutput` select the capture adapter/output; `None` uses the primary
  output. Moving across monitors pauses until the window returns to the selected output.
- The global quit key accepts a single ASCII letter or digit (case insensitive). The preview
  uses the same configured key. Caps Lock uses its toggle state. Exceptions, Ctrl+C, and preview
  exit all release capture and close preview windows. The static-desktop wait is bounded so
  the quit key remains responsive.
- `performanceDisplay = True` prints rolling mean and P95 times for capture, preprocessing,
  inference, postprocessing, and the complete iteration. CUDA synchronization makes stage
  timings meaningful but adds profiling overhead. `cpsDisplay` remains independently configurable.
- Startup prints the actual backend, provider/device, input size, and precision, then warms up
  the model. An unavailable requested ONNX provider is reported rather than silently selecting CPU.
- Dependencies must be installed explicitly; imports do not invoke pip. `requirements.txt`
  contains common dependencies and `requirements-onnx-*.txt` selects an optional ONNX backend.
  `requirements-py313.txt` applies the locally validated constraints and includes DirectML.

Run offline regression tests without opening capture or moving the mouse:

```powershell
python -m unittest discover -s tests -v
```

The tests cover color/layout conversion, masking, coordinates and target selection, model
metadata, unavailable providers, window moves/focus changes, timeout handling, and cleanup.
Actual CUDA/DirectML/TensorRT execution additionally depends on the installed driver/runtime;
unit tests use fakes for Windows capture and input.
