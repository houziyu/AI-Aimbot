"""Small Win32 boundary; no keyboard interception or injected software movement."""
import ctypes
from ctypes import wintypes
import os


class WindowClosedError(RuntimeError):
    """The user must select a new window; do not reuse a dead HWND."""


class WindowCaptureError(RuntimeError):
    """A temporary window geometry problem that can be retried."""


def user32():
    if os.name != "nt":
        raise RuntimeError("桌面辅助目前仅支持 Windows")
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.GetForegroundWindow.restype = wintypes.HWND
    api.IsWindow.argtypes = [wintypes.HWND]
    api.IsIconic.argtypes = [wintypes.HWND]
    api.IsWindowVisible.argtypes = [wintypes.HWND]
    api.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    api.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    api.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    return api


def list_windows():
    api = user32()
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def visit(hwnd, _):
        if api.IsWindowVisible(hwnd):
            length = api.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            api.GetWindowTextW(hwnd, title, length + 1)
            if title.value and not title.value.startswith("准星助手"):
                result.append((int(hwnd), title.value))
        return True

    api.EnumWindows(visit, 0)
    return result


def capture_region(hwnd, size, desktop):
    api = user32()
    if not hwnd or not api.IsWindow(hwnd):
        raise WindowClosedError("目标窗口已关闭，请重新选择")
    if api.IsIconic(hwnd) or api.GetForegroundWindow() != hwnd:
        return None
    rect, origin = wintypes.RECT(), wintypes.POINT()
    if not api.GetClientRect(hwnd, ctypes.byref(rect)) or not api.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise WindowCaptureError("无法读取目标窗口位置，正在等待窗口恢复")
    width, height = rect.right, rect.bottom
    if width < size or height < size:
        raise WindowCaptureError("目标窗口客户区小于截图范围；放大窗口，或停止后缩小截图尺寸")
    left = origin.x + width // 2 - size // 2
    top = origin.y + height // 2 - size // 2
    if left < desktop['left'] or top < desktop['top'] or left + size > desktop['left'] + desktop['width'] or top + size > desktop['top'] + desktop['height']:
        raise WindowCaptureError("截图区域超出桌面，请将目标窗口移回屏幕")
    return dict(left=left, top=top, width=size, height=size)
