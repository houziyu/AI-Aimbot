import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEvent
import aim_assist.runtime as backend
import aim_assist.ui as ui
from aim_assist.settings import Settings, load_settings, save_settings


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance
    instance.processEvents()


def test_ui_navigation_settings_and_initial_state(monkeypatch, tmp_path, app):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(backend, "CONFIG_PATH", path)
    monkeypatch.setattr(ui, "load_settings", lambda: Settings())
    monkeypatch.setattr(ui, "save_settings", lambda settings: save_settings(settings, path))
    window = ui.MainWindow()
    window.timer.stop()
    try:
        assert not window.power.isEnabled()
        assert window.connect_button.isEnabled()
        window.nav_buttons[1].click()
        assert window.pages.currentIndex() == 1
        window.inputs["confidence"].setValue(.65)
        assert not window.right_click_hotkey.isChecked()
        assert window.caps_lock_hotkey.isChecked()
        window.right_click_hotkey.setChecked(True)
        window.caps_lock_hotkey.setChecked(False)
        window.save_button.click()
        assert load_settings(path).confidence == .65
        assert load_settings(path).right_click_hotkey
        assert not load_settings(path).caps_lock_hotkey
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
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.mark.parametrize("right,caps", [(False, True), (True, False), (False, False), (True, True)])
def test_hotkey_switches_filter_edges_and_keep_f8(monkeypatch, tmp_path, right, caps, app):
    monkeypatch.setattr(backend, "CONFIG_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(ui, "load_settings", lambda: replace(Settings(), right_click_hotkey=right, caps_lock_hotkey=caps))
    window = ui.MainWindow()
    window.timer.stop()
    try:
        pressed = set()
        window.api = SimpleNamespace(GetAsyncKeyState=lambda key: 0x8000 if key in pressed else 0)
        window.key_down = dict.fromkeys((2, 20, 119), False)
        state = window.runtime.snapshot()
        state["connected"] = True
        monkeypatch.setattr(window.runtime, "snapshot", lambda: state)
        toggle = Mock()
        stop = Mock()
        monkeypatch.setattr(window, "toggle_active", toggle)
        monkeypatch.setattr(window.runtime, "set_active", stop)
        for key, enabled, source in ((2, right, "鼠标右键"), (20, caps, "Caps Lock")):
            toggle.reset_mock()
            pressed.add(key)
            window.tick()
            window.tick()
            if enabled:
                toggle.assert_called_once_with(source)
            else:
                toggle.assert_not_called()
            pressed.clear()
            window.tick()
        toggle.reset_mock()
        pressed.update((2, 20))
        window.tick()
        assert toggle.call_count == int(right or caps)
        if right or caps:
            toggle.assert_called_once_with("鼠标右键" if right else "Caps Lock")
        pressed.add(119)
        window.tick()
        stop.assert_called_once_with(False, "F8")
        assert toggle.call_count == int(right or caps)
        assert ("已禁用" in window.hotkey_labels["鼠标右键"].text()) == (not right)
    finally:
        window.runtime.shutdown()
        window.runtime.thread.join(3)
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
