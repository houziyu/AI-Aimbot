"""Window selection and bounded, focus-aware BetterCam capture."""

import time


def capture_region(window_rect, monitor_rect, width, height):
    """Translate desktop coordinates to coordinates local to the capture output."""
    left, top, right, bottom = window_rect
    ml, mt, mr, mb = monitor_rect
    if right - left < width or bottom - top < height:
        return None
    x = (left + right) // 2 - width // 2
    y = (top + bottom) // 2 - height // 2
    if x < ml or y < mt or x + width > mr or y + height > mb:
        return None
    return x - ml, y - mt, x - ml + width, y - mt + height


class CaptureSession:
    def __init__(self, camera, hwnd, settings, windows, monitor_rect):
        self.camera = camera
        self.hwnd = hwnd
        self.settings = settings
        self.windows = windows
        self.monitor_rect = monitor_rect
        self.region = None
        self.revision = 0
        self.running = False
        self.closed = False
        self.pause_reason = None

    def _window_region(self):
        if not self.windows.IsWindow(self.hwnd) or self.windows.IsIconic(self.hwnd):
            return None
        left, top, right, bottom = self.windows.GetClientRect(self.hwnd)
        origin = self.windows.ClientToScreen(self.hwnd, (left, top))
        end = self.windows.ClientToScreen(self.hwnd, (right, bottom))
        return capture_region((*origin, *end), self.monitor_rect,
                              self.settings.screenShotWidth, self.settings.screenShotHeight)

    def is_current(self):
        return (not self.closed and self.windows.IsWindow(self.hwnd)
                and self.windows.GetForegroundWindow() == self.hwnd
                and self.region is not None and self._window_region() == self.region)

    def read(self):
        if not self.windows.IsWindow(self.hwnd):
            raise RuntimeError("The selected window has been closed")
        region = self._window_region()
        reason = None
        if self.windows.GetForegroundWindow() != self.hwnd:
            reason = "Selected window is not in the foreground"
        elif region is None:
            reason = "Window is minimized, too small, or outside the selected capture output"
        if reason:
            if self.running:
                self.camera.stop()
                self.running = False
            if reason != self.pause_reason:
                print(f"Capture paused: {reason}")
                self.pause_reason = reason
            time.sleep(0.05)
            return None
        self.pause_reason = None
        if not self.running or region != self.region:
            if self.running:
                self.camera.stop()
            self.camera.region = region
            self.camera.start(region=region, target_fps=self.settings.captureFps, video_mode=False)
            self.running = True
            self.region = region
            self.revision += 1
        # BetterCam 1.0.0 has no timeout in get_latest_frame. Keep its version-specific
        # event access here so hotkeys remain responsive when the desktop is static.
        available = self.camera._BetterCam__frame_available
        if not available.wait(timeout=0.1):
            if not self.camera.is_capturing:
                raise RuntimeError("The screen capture worker stopped unexpectedly")
            return None
        if not self.camera.is_capturing:
            raise RuntimeError("The screen capture worker stopped unexpectedly")
        return self.camera.get_latest_frame()

    def close(self):
        if not self.closed:
            self.closed = True
            self.camera.release()
            self.running = False


def select_window():
    import pygetwindow

    windows = [window for window in pygetwindow.getAllWindows() if window.title.strip()]
    if not windows:
        raise RuntimeError("No titled windows are available")
    for index, window in enumerate(windows):
        print(f"[{index}]: {window.title}")
    while True:
        try:
            index = int(input("Select a window number: "))
            if 0 <= index < len(windows):
                break
        except ValueError:
            pass
        print(f"Enter a number between 0 and {len(windows) - 1}.")
    window = windows[index]
    if window.isMinimized:
        window.restore()
    for attempt in range(5):
        try:
            window.activate()
            return window
        except pygetwindow.PyGetWindowException:
            if attempt == 4:
                raise RuntimeError("Could not activate the selected window; switch to it and retry")
            time.sleep(0.5)


def open_capture(settings):
    import win32api
    import win32gui
    import bettercam

    window = select_window()
    camera = bettercam.create(device_idx=settings.captureDevice, output_idx=settings.captureOutput,
                              output_color="BGRA", max_buffer_len=settings.captureBuffer)
    if camera is None:
        raise RuntimeError("BetterCam could not create a screen capture device")
    try:
        # BetterCam 1.0.0 exposes output geometry through its DXGI output object.
        monitor_rect = win32api.GetMonitorInfo(camera._output.hmonitor)["Monitor"]
        capture = CaptureSession(camera, window._hWnd, settings, win32gui, monitor_rect)
        if capture._window_region() is None:
            raise ValueError("Window does not fit the capture output. Check captureDevice/captureOutput and screenshot dimensions.")
        return capture
    except BaseException:
        camera.release()
        raise


def gameSelection():
    """Compatibility helper for community scripts using the original tuple API."""
    import config
    from runtime import Settings

    settings = Settings.from_module(config)
    capture = open_capture(settings)
    try:
        # Keep the original camera API (including repeated frames) for independent
        # community scripts that do not poll CaptureSession.read() for timeouts.
        region = capture._window_region()
        capture.camera.region = region
        capture.camera.start(region=region, target_fps=settings.captureFps, video_mode=True)
        return capture.camera, *settings.center
    except BaseException:
        capture.close()
        raise
