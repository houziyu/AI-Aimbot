import os
from types import SimpleNamespace
from unittest.mock import Mock
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
import aim_assist.runtime as backend
import aim_assist.ui as ui
from aim_assist.settings import Settings, load_settings, save_settings


def test_ui_navigation_settings_and_initial_state(monkeypatch, tmp_path):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(backend, "CONFIG_PATH", path)
    monkeypatch.setattr(ui, "load_settings", lambda: Settings())
    monkeypatch.setattr(ui, "save_settings", lambda settings: save_settings(settings, path))
    app = QApplication.instance() or QApplication([])
    window = ui.MainWindow()
    window.timer.stop()
    try:
        assert not window.power.isEnabled()
        assert window.connect_button.isEnabled()
        window.nav_buttons[1].click()
        assert window.pages.currentIndex() == 1
        window.inputs["confidence"].setValue(.65)
        window.save_button.click()
        assert load_settings(path).confidence == .65
        window.rate_buttons[0].click()
        assert load_settings(path).rate == 30
        window.model_path.setText(str(tmp_path / "missing.onnx"))
        window.save_button.click()
        assert "存在" in window.settings_feedback.text()
        assert load_settings(path).model == Settings().model
        window.nav_buttons[2].click()
        window.render()
        assert window.log_list.count() > 0
        # Rising-edge hotkeys: hold does not repeat, and F8 wins simultaneous keys.
        pressed = set()
        window.api = SimpleNamespace(GetAsyncKeyState=lambda key: 0x8000 if key in pressed else 0)
        window.key_down = {2: False, 20: False, 119: False}
        base = window.runtime.snapshot()
        base["connected"] = True
        monkeypatch.setattr(window.runtime, "snapshot", lambda: base)
        toggle = Mock()
        stop = Mock()
        monkeypatch.setattr(window, "toggle_active", toggle)
        monkeypatch.setattr(window.runtime, "set_active", stop)
        pressed.add(2)
        window.tick()
        window.tick()
        toggle.assert_called_once_with("鼠标右键")
        pressed.clear()
        window.tick()
        pressed.update((20, 119))
        window.tick()
        stop.assert_called_once_with(False, "F8")
        assert toggle.call_count == 1
    finally:
        window.runtime.shutdown()
        window.runtime.thread.join(3)
        window.close()
        app.processEvents()
