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
    monkeypatch.setattr(ui, "CONFIG_PATH", path)
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
        assert window.cpu_threads.value() == 0
        window.cpu_threads.setValue(8)
        assert not window.right_click_hotkey.isChecked()
        assert window.caps_lock_hotkey.isChecked()
        window.right_click_hotkey.setChecked(True)
        window.caps_lock_hotkey.setChecked(False)
        window.save_button.click()
        assert load_settings(path).confidence == .65
        assert load_settings(path).cpu_threads == 8
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
    monkeypatch.setattr(ui, "CONFIG_PATH", tmp_path / "settings.json")
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


@pytest.fixture
def window(monkeypatch, tmp_path, app):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(ui, "CONFIG_PATH", path)
    monkeypatch.setattr(backend, "CONFIG_PATH", path)
    monkeypatch.setattr(ui, "load_settings", lambda: Settings())
    monkeypatch.setattr(ui, "save_settings", lambda settings: save_settings(settings, path))
    instance = ui.MainWindow()
    instance.timer.stop()
    try:
        yield instance
    finally:
        instance.runtime.shutdown()
        instance.runtime.thread.join(3)
        instance.close()
        instance.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def test_output_note_keeps_last_run_counts_after_device_error(window, monkeypatch):
    state = window.runtime.snapshot()
    state["status"] = "device_error"
    state["metrics"].update(moves=5, accepted=2, rejected=2, rejected_expired=1,
                            rejected_busy=1, ack_timeouts=1, expired=3, xy1_output=True)
    monkeypatch.setattr(window.runtime, "snapshot", lambda: state)
    window.render()
    note = window.output_note.text()
    assert "上次运行" in note and "串口写入 5 条" in note
    assert "固件接受 2 条" in note and "拒绝 2 条" in note
    assert "未确认 1 条" in note and "回执超时 1" in note
    assert "过期 1 · 忙碌 1" in note and "电脑端过期 3 帧" in note


def test_profile_load_copy_defaults_and_undo(window, tmp_path):
    from aim_assist.profiles import load_profiles
    window.inputs["confidence"].setValue(.7)
    window.settings_rate.setCurrentIndex(window.settings_rate.findData(120))
    window.profile_name.setText("窗口 A")
    window.profile_save.click()
    assert window.settings.confidence == .4  # Saving a profile does not apply it.
    window.profile_copy.click()
    assert set(load_profiles(tmp_path / "profiles.json")) == {"窗口 A", "窗口 A 副本"}
    window.defaults_button.click()
    assert window.inputs["confidence"].value() == .4
    window.profile_combo.setCurrentIndex(window.profile_combo.findData("窗口 A"))
    window.profile_load.click()
    assert window.inputs["confidence"].value() == .7
    assert window.settings.confidence == .4
    window.save_button.click()
    assert load_settings(tmp_path / "settings.json").rate == 120
    window.render()
    assert window.undo_button.isEnabled()
    window.undo_button.click()
    assert load_settings(tmp_path / "settings.json").confidence == .4
    assert window.settings_rate.currentData() == 60
    window.render()
    assert not window.undo_button.isEnabled()
    assert len(load_profiles(tmp_path / "profiles.json")) == 2


def test_save_failure_rolls_back_runtime_and_preserves_undo(window, monkeypatch):
    window.inputs["confidence"].setValue(.7)
    window.save_button.click()
    previous = window.previous_settings

    def fail(settings):
        raise OSError("disk full")

    monkeypatch.setattr(ui, "save_settings", fail)
    window.inputs["confidence"].setValue(.8)
    window.save_button.click()
    assert window.settings.confidence == .7
    assert window.runtime.settings.confidence == .7
    assert window.previous_settings == previous
    assert "disk full" in window.settings_feedback.text()


def test_preview_ui_without_device_and_hotkey_isolation(window, monkeypatch):
    assert window.preview_button.isEnabled()
    assert not window.power.isEnabled()
    window.window.addItem("test window", 42)
    window.window.setCurrentIndex(window.window.findData(42))
    configure, preview = Mock(), Mock()
    monkeypatch.setattr(window.runtime, "configure", configure)
    monkeypatch.setattr(window.runtime, "set_preview", preview)
    window.preview_button.click()
    configure.assert_called_once_with(window.settings, 42)
    preview.assert_called_once_with(True)
    state = window.runtime.snapshot()
    state.update(connected=True, preview_enabled=True, status="preview")
    monkeypatch.setattr(window.runtime, "snapshot", lambda: state)
    window.render()
    assert window.power_label.text() == "仅识别预览"
    assert not window.power.isEnabled()
    assert not window.save_button.isEnabled()
    assert window.preview_button.text() == "停止预览"
    pressed = {20}
    window.api = SimpleNamespace(GetAsyncKeyState=lambda key: 0x8000 if key in pressed else 0)
    window.key_down = dict.fromkeys((2, 20, 119), False)
    toggle, stop = Mock(), Mock()
    monkeypatch.setattr(window, "toggle_active", toggle)
    monkeypatch.setattr(window.runtime, "set_active", stop)
    window.tick()
    toggle.assert_not_called()
    pressed.add(119)
    window.tick()
    stop.assert_called_once_with(False, "F8")


def test_status_and_optional_sound_follow_transitions(window, monkeypatch):
    beep = Mock()
    monkeypatch.setattr(ui.QApplication, "beep", beep)
    state = window.runtime.snapshot()
    monkeypatch.setattr(window.runtime, "snapshot", lambda: state)
    state.update(status="waiting_window", notice=1)
    window.render()
    assert window.power_label.text() == "等待窗口"
    beep.assert_not_called()
    window.settings = replace(window.settings, sound_enabled=True)
    state.update(status="model_error", notice=2)
    window.render()
    window.render()
    assert window.power_label.text() == "模型错误"
    beep.assert_called_once()


def test_hotkeys_keep_polling_between_throttled_renders(window, monkeypatch):
    render, stop = Mock(), Mock()
    monkeypatch.setattr(window, "render", render)
    monkeypatch.setattr(window.runtime, "set_active", stop)
    pressed = set()
    window.api = SimpleNamespace(GetAsyncKeyState=lambda key: 0x8000 if key in pressed else 0)
    window.key_down = dict.fromkeys((2, 20, 119), False)
    window.next_render_at = float("inf")
    window.tick()
    render.assert_not_called()
    pressed.add(119)
    window.tick()
    stop.assert_called_once_with(False, "F8")
    render.assert_called_once()


def test_unchanged_labels_do_not_trigger_updates(window):
    widget = Mock()
    widget.text.return_value = "same"
    window._text(widget, "same")
    widget.setText.assert_not_called()
    window._text(widget, "new")
    widget.setText.assert_called_once_with("new")
