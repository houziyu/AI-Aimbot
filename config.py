# Portion of screen to be captured (This forms a square/rectangle around the center of screen)
screenShotHeight = 320
screenShotWidth = 320

# Use "left" or "right" for the mask side depending on where the interfering object is, useful for 3rd player models or large guns
useMask = False
maskSide = "left"
maskWidth = 80
maskHeight = 200

# Autoaim mouse movement amplifier
aaMovementAmp = .4

# Time-normalized control: .4 is the correction fraction at this reference FPS.
# aaMovementAmp must now be in [0, 1]. These are starting values, not Apex calibration.
controlReferenceFps = 120.0
controlMaxIntervalMs = 50.0  # Never accumulate a large correction after a stall
movementDeadzone = 1.5  # Screenshot pixels, radial
maxMovePerFrame = 40  # Maximum length of each relative mouse command
targetMemoryMs = 250.0  # Keep selection only during a short wait for a NEW frame
maxFrameAgeMs = 80.0  # Discard old frames/results; includes capture and processing
targetClasses = (0,)  # Must match the model's labels; COCO class 0 is person
headAimOffset = 0.38  # Fraction of box height ABOVE its center, [0, 0.5]
bodyAimOffset = 0.2
targetRadius = 140.0  # Screenshot pixels from center to aim point; 0 disables the limit

# Person Class Confidence
confidence = 0.4

# What key to press to quit and shutdown the autoaim
aaQuitKey = "Q"

# If you want to main slightly upwards towards the head
headshot_mode = True

# Displays the Corrections per second in the terminal
cpsDisplay = True

# Set to True if you want to get the visuals
visuals = False

# Smarter selection of people
centerOfScreen = True

# MAIN.PY ONLY - Local weights file, downloaded automatically on first run if missing
# Use yolov5m.pt / yolov5l.pt for better accuracy at the cost of speed
modelWeights = "yolov5s.pt"

# ONNX ONLY - Choose 1 of the 3 below
# 1 - CPU
# 2 - AMD
# 3 - NVIDIA
onnxChoice = 1

# NMS overlap threshold, separate from detection confidence
iouThreshold = 0.45
maxDetections = 100

# Model paths; relative paths are resolved from the project folder
onnxWeights = "yolov5s320Half.onnx"
tensorrtWeights = "yolov5s320Half.engine"

# Capture settings; the shared loop uses one timestamped latest-frame slot.
captureFps = 120
captureBuffer = 4  # Legacy gameSelection() camera API only
captureDevice = 0
captureOutput = None  # None selects the primary output; use an output index for other monitors

# Print rolling average and P95 timings. GPU synchronization adds profiling overhead.
performanceDisplay = False
