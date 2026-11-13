"""Native adaptation of the supplied three-page Aim Assist UI prototype."""
from dataclasses import replace
import os
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QPushButton, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)
import serial.tools.list_ports

from .runtime import Runtime
from .profiles import load_profiles, save_profile
from .settings import CONFIG_PATH, ROOT, Settings, load_settings, save_settings
from .windows import list_windows, user32


STYLE = """
QWidget { color:#202a32; font-family:'Microsoft YaHei UI','Segoe UI'; font-size:13px; }
QMainWindow, QStackedWidget, QScrollArea { background:#f5f6f8; }
QWidget#page { background:#f5f6f8; }
QFrame#sidebar, QFrame#header { background:#ffffff; border:0; }
QFrame#card { background:#ffffff; border:1px solid #e2e7eb; border-radius:14px; }
QLabel { background:transparent; border:0; }
QLabel#title { font-size:25px; font-weight:600; }
QLabel#brand { font-size:17px; font-weight:600; }
QLabel#heading { font-size:15px; font-weight:600; }
QLabel#muted { color:#65717d; font-size:12px; }
QLabel#value { font-size:24px; font-weight:600; }
QLabel#chip { color:#09796c; background:#e5f4ef; padding:8px 14px; border-radius:15px; }
QLabel#preview { background:#f5f6f8; color:#65717d; border:1px dashed #c9d4d9; border-radius:8px; }
QPushButton { background:#ffffff; border:1px solid #e2e7eb; padding:10px 15px; border-radius:8px; }
QPushButton:hover { background:#edf1f4; }
QPushButton:checked, QPushButton#primary { background:#09796c; color:white; border-color:#09796c; }
QPushButton#nav { text-align:left; border:0; padding:13px 16px; }
QPushButton#nav:checked { background:#e5f4ef; color:#09796c; font-weight:600; }
QPushButton:disabled { color:#a4aca0; background:#f0f2ed; border-color:#e5e9e1; }
QPushButton#primary:disabled { color:#9ba6aa; background:#e8eeeb; border-color:#e8eeeb; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { background:#f5f6f8; border:1px solid #e2e7eb; border-radius:7px; padding:8px; min-height:18px; }
QComboBox::drop-down { border:0; width:22px; }
QComboBox QAbstractItemView { background:white; selection-background-color:#e2ecd9; selection-color:#29332d; }
QListWidget { background:#ffffff; border:0; padding:8px; }
QListWidget::item { padding:12px; border-bottom:1px solid #edf0e9; }
QCheckBox { spacing:8px; }
QScrollArea { border:0; }
QToolTip { background:#ffffff; color:#29332d; border:1px solid #cad5c3; }
"""


def label(text, name="", wrap=False):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback, name=""):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(callback)
    return widget


def card(title):
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(10)
    layout.addWidget(label(title, "heading"))
    return widget, layout


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("准星助手 · ESP32")
        self.resize(1120, 940)
        self.setMinimumSize(940, 720)
        initial_error = ""
        try:
            self.settings = load_settings()
        except (ValueError, TypeError, OSError) as exc:
            self.settings = Settings()
            initial_error = f"配置读取失败，已使用默认值（原文件保留）：{exc}"
        self.runtime = Runtime(self.settings)
        self.previous_settings = None
        self.last_notice = 0
        self.last_image = None
        self.last_preview_size = None
        self.next_render_at = 0.
        self.last_logs = None
        self.last_message = ""
        self.closing = False
        self.api = user32() if os.name == "nt" else None
        self.key_down = {key: bool(self.api.GetAsyncKeyState(key) & 0x8000) if self.api else False for key in (2, 20, 119)}
        self.controls = []
        self.build()
        self.refresh_devices()
        self.refresh_windows()
        self.refresh_profiles()
        if initial_error:
            self.runtime.log(initial_error)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(20)
        self.render()

    def build(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame()
        header.setObjectName("header")
        row = QHBoxLayout(header)
        row.setContentsMargins(24, 16, 24, 16)
        row.addWidget(label("⊕  准星助手", "brand"))
        row.addWidget(label("ESP32 · 蓝牙 HID", "muted"))
        row.addStretch()
        row.addWidget(label("本地运行", "chip"))
        outer.addWidget(header)
        shell = QHBoxLayout()
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(168)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(12, 25, 12, 20)
        self.pages = QStackedWidget()
        self.nav_buttons = []
        for index, text in enumerate(("控制台", "参数设置", "运行记录")):
            item = button(text, lambda checked=False, i=index: self.navigate(i), "nav")
            item.setCheckable(True)
            item.setChecked(index == 0)
            self.nav_buttons.append(item)
            nav.addWidget(item)
        nav.addStretch()
        nav.addWidget(label("本地运行\n图像识别 · 设备控制", "muted", True))
        shell.addWidget(sidebar)
        shell.addWidget(self.pages, 1)
        outer.addLayout(shell, 1)
        self.footer = label("", "muted")
        self.footer.setContentsMargins(22, 10, 22, 10)
        outer.addWidget(self.footer)
        self.setCentralWidget(root)
        self.build_home()
        self.build_settings()
        self.build_logs()

    def page(self, title, subtitle):
        widget = QWidget()
        widget.setObjectName("page")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(label(title, "title"))
        layout.addWidget(label(subtitle, "muted"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        self.pages.addWidget(scroll)
        return layout

    def build_home(self):
        layout = self.page("控制台", "连接设备，随时切换辅助状态。")
        device, box = card("ESP32 设备连接")
        fields = QGridLayout()
        fields.addWidget(label("鼠标输出方式", "muted"), 0, 0)
        fields.addWidget(label("指令串口", "muted"), 0, 1)
        transport = QComboBox()
        transport.addItem("蓝牙 HID · 自动识别固件")
        transport.addItem("USB HID · 需匹配固件")
        transport.model().item(1).setEnabled(False)
        transport.setToolTip("自动识别 XY 双轴可变位移固件；兼容旧版方向固件。")
        self.port = QComboBox()
        self.port.setMinimumWidth(160)
        self.port.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.port.setMinimumContentsLength(18)
        self.connect_button = button("连接设备", self.toggle_connection, "primary")
        self.refresh_button = button("刷新", self.refresh_devices)
        fields.addWidget(transport, 1, 0)
        fields.addWidget(self.port, 1, 1)
        fields.addWidget(self.refresh_button, 1, 2)
        fields.addWidget(self.connect_button, 1, 3)
        fields.setColumnStretch(0, 2)
        fields.setColumnStretch(1, 3)
        box.addLayout(fields)
        self.device_status = label("设备未连接", "muted", True)
        box.addWidget(self.device_status)
        target_row = QHBoxLayout()
        target_row.addWidget(label("目标窗口", "muted"))
        self.window = QComboBox()
        self.window.setMinimumWidth(210)
        self.window.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.window.setMinimumContentsLength(24)
        target_row.addWidget(self.window, 1)
        self.window_refresh = button("刷新窗口", self.refresh_windows)
        target_row.addWidget(self.window_refresh)
        box.addLayout(target_row)
        layout.addWidget(device)
        workspace = QHBoxLayout()
        workspace.setSpacing(18)
        assist, left = card("辅助控制")
        power_row = QHBoxLayout()
        self.power_label = label("已关闭", "value")
        power_row.addWidget(self.power_label)
        power_row.addStretch()
        self.power = button("开启辅助", lambda: self.toggle_active("界面"), "primary")
        power_row.addWidget(self.power)
        left.addLayout(power_row)
        self.preview_button = button("仅识别预览", self.toggle_preview)
        self.preview_button.setToolTip("无需连接设备。只显示检测结果，不发送位移；F8 可停止。")
        left.addWidget(self.preview_button)
        self.detail = label("", "muted", True)
        self.detail.setMinimumHeight(36)
        left.addWidget(self.detail)
        left.addWidget(label("辅助快捷键", "heading"))
        keys = QHBoxLayout()
        self.hotkey_labels = {}
        for name in ("鼠标右键", "Caps Lock"):
            key = label("", "chip")
            key.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.hotkey_labels[name] = key
            keys.addWidget(key)
        left.addLayout(keys)
        left.addWidget(label("F8 停止辅助与预览", "muted"))
        left.addStretch()
        left.addWidget(label("识别频率上限 · 次 / 秒", "muted"))
        rates = QHBoxLayout()
        self.rate_buttons = []
        for rate in (30, 60, 120):
            item = button(str(rate), lambda checked=False, r=rate: self.set_rate(r))
            item.setCheckable(True)
            item.setChecked(rate == self.settings.rate)
            self.rate_buttons.append(item)
            rates.addWidget(item)
        left.addLayout(rates)
        workspace.addWidget(assist, 1)
        preview_card, right = card("识别预览")
        self.preview = label("＋\n\n辅助关闭 · 预览暂停", "preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(220, 220)
        right.addWidget(self.preview, 1)
        self.preview_note = label("目标窗口中心 320 × 320 · 真实截图", "muted")
        right.addWidget(self.preview_note)
        workspace.addWidget(preview_card, 1)
        layout.addLayout(workspace, 1)
        metrics, metrics_box = card("性能监测")
        stats = QGridLayout()
        self.metric_labels = {}
        specifications = (("fps", "实际识别频率", "次 / 秒 · 最近 1 秒"),
                          ("output_fps", "串口写入频率", "条 / 秒 · 最近 1 秒"),
                          ("capture", "截图耗时", "ms · 最近一帧"),
                          ("inference", "模型推理耗时", "ms · 仅模型执行"),
                          ("serial", "串口写入耗时", "ms · 最近一次发送"),
                          ("ack", "设备回执等待", "ms · 最近一次位移回执"))
        for index, (key, title, note) in enumerate(specifications):
            column = QVBoxLayout()
            column.addWidget(label(title, "muted"))
            value = label("—", "value")
            self.metric_labels[key] = value
            column.addWidget(value)
            column.addWidget(label(note, "muted"))
            stats.addLayout(column, index // 3, index % 3)
            stats.setColumnStretch(index % 3, 1)
        metrics_box.addLayout(stats)
        self.latency_note = label("", "muted", True)
        metrics_box.addWidget(self.latency_note)
        self.stages_note = label("", "muted", True)
        metrics_box.addWidget(self.stages_note)
        self.output_note = label("", "muted", True)
        metrics_box.addWidget(self.output_note)
        metrics_box.addWidget(label("回执等待含电脑轮询间隔；固件接受表示报告已交给蓝牙栈。", "muted", True))
        layout.addWidget(metrics)

    def build_settings(self):
        layout = self.page("参数设置", "停止辅助与预览后调整，点击保存应用。配置保存在本机。")
        profiles, box = card("参数方案")
        row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumContentsLength(12)
        self.profile_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.profile_load = button("载入方案", self.load_profile)
        self.profile_copy = button("复制当前参数", self.copy_profile)
        row.addWidget(self.profile_combo, 1)
        row.addWidget(self.profile_load)
        row.addWidget(self.profile_copy)
        box.addLayout(row)
        row = QHBoxLayout()
        self.profile_name = QLineEdit()
        self.profile_name.setPlaceholderText("方案名称，例如：桌面测试")
        self.profile_name.setMaxLength(40)
        self.profile_save = button("保存 / 覆盖方案", self.store_profile)
        row.addWidget(self.profile_name, 1)
        row.addWidget(self.profile_save)
        box.addLayout(row)
        box.addWidget(label("方案保存当前表单参数。同名保存会覆盖；载入后点击底部“保存并应用”生效。", "muted", True))
        layout.addWidget(profiles)
        model_card, box = card("模型与计算")
        self.model_path = QLineEdit(self.settings.model)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_path, 1)
        self.browse_button = button("选择 ONNX", self.browse_model)
        model_row.addWidget(self.browse_button)
        box.addWidget(label("识别模型 · YOLOv5 原始输出，类别 0 为人物", "muted"))
        box.addLayout(model_row)
        self.provider = QComboBox()
        import onnxruntime as ort
        available = ort.get_available_providers()
        for text, value in (("CPU", "CPUExecutionProvider"), ("DirectML · AMD / Intel / NVIDIA", "DmlExecutionProvider"), ("CUDA · NVIDIA", "CUDAExecutionProvider")):
            self.provider.addItem(text + ("" if value in available else "（未安装）"), value)
            if value not in available:
                self.provider.model().item(self.provider.count() - 1).setEnabled(False)
        self.provider.setCurrentIndex(max(0, self.provider.findData(self.settings.provider)))
        box.addWidget(label("计算设备", "muted"))
        box.addWidget(self.provider)
        self.cpu_threads = QSpinBox()
        self.cpu_threads.setRange(0, 256)
        self.cpu_threads.setSpecialValueText("自动（ONNX Runtime 默认）")
        self.cpu_threads.setValue(self.settings.cpu_threads)
        box.addWidget(label("CPU 推理线程数", "muted"))
        box.addWidget(self.cpu_threads)
        self.settings_rate = QComboBox()
        for rate in (30, 60, 120):
            self.settings_rate.addItem(f"{rate} 次 / 秒", rate)
        self.settings_rate.setCurrentIndex(self.settings_rate.findData(self.settings.rate))
        box.addWidget(label("识别频率上限", "muted"))
        box.addWidget(self.settings_rate)
        layout.addWidget(model_card)
        hotkeys, box = card("辅助快捷键")
        self.right_click_hotkey = QCheckBox("鼠标右键按下时切换辅助")
        self.right_click_hotkey.setChecked(self.settings.right_click_hotkey)
        self.caps_lock_hotkey = QCheckBox("Caps Lock 按下时切换辅助")
        self.caps_lock_hotkey.setChecked(self.settings.caps_lock_hotkey)
        box.addWidget(self.right_click_hotkey)
        box.addWidget(self.caps_lock_hotkey)
        self.sound_enabled = QCheckBox("开启、停止或异常时播放提示音")
        self.sound_enabled.setChecked(self.settings.sound_enabled)
        box.addWidget(self.sound_enabled)
        box.addWidget(label("右键用于开镜时，建议关闭右键快捷键，使用 Caps Lock 控制辅助。F8 随时关闭辅助。", "muted", True))
        layout.addWidget(hotkeys)
        parameters, box = card("辅助参数")
        grid = QGridLayout()
        self.inputs = {}
        specs = (("strength", "移动倍率", .05, 1., .05), ("confidence", "识别置信度", .1, .95, .05),
                 ("aim_height", "瞄准高度 · 从框顶部计，0.30 为上身", .05, .5, .01), ("deadzone", "死区 · 截图像素", 0, 100, 1),
                 ("radius", "选取半径 · 截图像素", 10, 640, 5), ("crop_size", "截图边长 · 像素", 160, 1280, 32),
                 ("max_step", "每轴修正上限 · counts", 1, 100, 1), ("mask_width", "遮罩宽度 · 像素", 0, 1280, 10),
                 ("mask_height", "遮罩高度 · 像素", 0, 1280, 10), ("output_rate", "位移发送上限 · 条 / 秒", 30, 60, 5),
                 ("result_max_age_ms", "结果有效期 · 毫秒", 20, 500, 10))
        for index, (key, text, low, high, step) in enumerate(specs):
            field = QDoubleSpinBox() if isinstance(low, float) else QSpinBox()
            field.setRange(low, high)
            field.setSingleStep(step)
            field.setValue(getattr(self.settings, key))
            self.inputs[key] = field
            row, col = index // 2 * 2, index % 2
            grid.addWidget(label(text, "muted"), row, col)
            grid.addWidget(field, row + 1, col)
        box.addLayout(grid)
        mask_row = QHBoxLayout()
        self.mask = QCheckBox("启用底部遮罩")
        self.mask.setChecked(self.settings.mask)
        self.mask_side = QComboBox()
        self.mask_side.addItem("左下角", "left")
        self.mask_side.addItem("右下角", "right")
        self.mask_side.setCurrentIndex(self.mask_side.findData(self.settings.mask_side))
        mask_row.addWidget(self.mask)
        mask_row.addWidget(self.mask_side)
        box.addLayout(mask_row)
        box.addWidget(label("XY 固件支持双轴可变位移，倍率和修正上限直接影响位移。旧版方向固件每步约 10 counts。", "muted", True))
        layout.addWidget(parameters)
        self.save_button = button("保存并应用", self.apply_settings, "primary")
        self.settings_feedback = label("", "muted", True)
        layout.addWidget(self.settings_feedback)
        recovery = QHBoxLayout()
        self.defaults_button = button("载入默认参数", self.restore_defaults)
        self.undo_button = button("撤销上次应用", self.undo_settings)
        recovery.addWidget(self.defaults_button)
        recovery.addWidget(self.undo_button)
        layout.addLayout(recovery)
        layout.addWidget(self.save_button)
        layout.addStretch()
        self.controls = [self.model_path, self.browse_button, self.provider, self.mask, self.mask_side,
                         self.right_click_hotkey, self.caps_lock_hotkey, self.sound_enabled, self.settings_rate,
                         self.save_button, self.defaults_button, self.profile_combo, self.profile_name,
                         self.profile_load, self.profile_save, self.profile_copy, *self.inputs.values()]
        self.provider.currentIndexChanged.connect(self.update_cpu_threads_control)

    def update_cpu_threads_control(self):
        self._enabled(self.cpu_threads, self.provider.isEnabled() and self.provider.currentData() == "CPUExecutionProvider")

    def build_logs(self):
        layout = self.page("运行记录", "连接、状态切换、参数调整与错误详情。")
        box, content = card("最近事件 · 最多 200 条")
        self.log_list = QListWidget()
        self.log_list.setWordWrap(True)
        content.addWidget(self.log_list)
        layout.addWidget(box, 1)
        layout.addWidget(button("打开日志文件夹", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(CONFIG_PATH.parent)))))

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        for i, item in enumerate(self.nav_buttons):
            item.setChecked(i == index)

    def report_error(self, exc):
        self.runtime.log(str(exc))
        self.detail.setText(str(exc))
        self.settings_feedback.setText(str(exc))
        self.last_message = self.runtime.snapshot()["message"]

    def refresh_devices(self):
        selected = self.port.currentData() or self.settings.port
        self.port.clear()
        for port in serial.tools.list_ports.comports():
            self.port.addItem(f"{port.device} · {port.description}", port.device)
        index = self.port.findData(selected)
        if index >= 0:
            self.port.setCurrentIndex(index)
        if not self.port.count():
            self.port.addItem("未发现串口", "")

    def refresh_windows(self):
        selected = self.window.currentData()
        self.window.clear()
        self.window.addItem("请选择需要识别的窗口", 0)
        if self.api:
            for hwnd, title in list_windows():
                self.window.addItem(title[:100], hwnd)
        index = self.window.findData(selected)
        if index >= 0:
            self.window.setCurrentIndex(index)

    def toggle_connection(self):
        try:
            if self.runtime.snapshot()["connected"]:
                self.runtime.disconnect()
            else:
                self.runtime.connect(self.port.currentData())
        except Exception as exc:
            self.report_error(exc)

    def toggle_active(self, source):
        try:
            active = self.runtime.snapshot()["active"]
            if not active:
                self.runtime.configure(self.settings, self.window.currentData() or 0)
            self.runtime.set_active(not active, source)
        except Exception as exc:
            self.report_error(exc)

    def toggle_preview(self):
        try:
            enabled = self.runtime.snapshot()["preview_enabled"]
            if not enabled:
                self.runtime.configure(self.settings, self.window.currentData() or 0)
            self.runtime.set_preview(not enabled)
        except Exception as exc:
            self.report_error(exc)

    def set_rate(self, rate):
        try:
            updated = replace(self.settings, rate=rate)
            self.commit_settings(updated)
            self.settings_rate.setCurrentIndex(self.settings_rate.findData(rate))
            self.runtime.log(f"识别频率上限：{rate} 次 / 秒")
        except Exception as exc:
            self.report_error(exc)

    def browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 YOLOv5 ONNX 模型", str(ROOT), "ONNX 模型 (*.onnx)")
        if path:
            self.model_path.setText(path)

    def read_form(self):
        path = Path(self.model_path.text()).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != ".onnx":
            raise ValueError("请选择存在的 .onnx 模型文件")
        return replace(self.settings, model=str(path), provider=self.provider.currentData(), port=self.port.currentData() or "",
                       rate=self.settings_rate.currentData(), cpu_threads=self.cpu_threads.value(),
                       sound_enabled=self.sound_enabled.isChecked(),
                       right_click_hotkey=self.right_click_hotkey.isChecked(), caps_lock_hotkey=self.caps_lock_hotkey.isChecked(),
                       mask=self.mask.isChecked(), mask_side=self.mask_side.currentData(),
                       **{key: widget.value() for key, widget in self.inputs.items()}).validate()

    def fill_form(self, settings):
        self.model_path.setText(settings.model)
        self.provider.setCurrentIndex(self.provider.findData(settings.provider))
        self.cpu_threads.setValue(settings.cpu_threads)
        self.settings_rate.setCurrentIndex(self.settings_rate.findData(settings.rate))
        self.sound_enabled.setChecked(settings.sound_enabled)
        self.right_click_hotkey.setChecked(settings.right_click_hotkey)
        self.caps_lock_hotkey.setChecked(settings.caps_lock_hotkey)
        self.mask.setChecked(settings.mask)
        self.mask_side.setCurrentIndex(self.mask_side.findData(settings.mask_side))
        for key, widget in self.inputs.items():
            widget.setValue(getattr(settings, key))

    def commit_settings(self, updated, *, remember=True):
        old, hwnd = self.settings, self.runtime.hwnd
        self.runtime.configure(updated, self.window.currentData() or 0)
        try:
            save_settings(updated)
        except Exception:
            self.runtime.configure(old, hwnd)
            raise
        if remember and updated != old:
            self.previous_settings = old
        self.settings = updated

    def apply_settings(self):
        try:
            self.commit_settings(self.read_form())
            self.runtime.log("参数已保存并应用；模型在下次开启时加载。")
            self.settings_feedback.setText("已保存。下次开启辅助或预览时使用新参数。")
        except Exception as exc:
            self.report_error(exc)

    def refresh_profiles(self, selected=""):
        try:
            profiles = load_profiles(CONFIG_PATH.with_name("profiles.json"))
            self.profile_combo.clear()
            self.profile_combo.addItem("选择已保存方案", "")
            for name in sorted(profiles):
                self.profile_combo.addItem(name, name)
            self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(selected)))
        except Exception as exc:
            self.report_error(exc)

    def store_profile(self):
        try:
            name = self.profile_name.text().strip()
            save_profile(name, self.read_form(), CONFIG_PATH.with_name("profiles.json"))
            self.refresh_profiles(name)
            self.settings_feedback.setText(f"已保存方案“{name}”。当前运行参数未改变，点击保存并应用后生效。")
        except Exception as exc:
            self.report_error(exc)

    def copy_profile(self):
        try:
            profiles = load_profiles(CONFIG_PATH.with_name("profiles.json"))
            base = (self.profile_name.text().strip() or self.profile_combo.currentData() or "当前参数")[:30]
            name, index = f"{base} 副本", 2
            while name in profiles:
                name = f"{base} 副本 {index}"
                index += 1
            save_profile(name, self.read_form(), CONFIG_PATH.with_name("profiles.json"))
            self.profile_name.setText(name)
            self.refresh_profiles(name)
            self.settings_feedback.setText(f"当前表单已复制为“{name}”。")
        except Exception as exc:
            self.report_error(exc)

    def load_profile(self):
        try:
            name = self.profile_combo.currentData()
            profiles = load_profiles(CONFIG_PATH.with_name("profiles.json"))
            if name not in profiles:
                raise ValueError("请选择已保存的参数方案")
            self.fill_form(profiles[name])
            self.profile_name.setText(name)
            self.settings_feedback.setText(f"已载入“{name}”，点击保存并应用后生效。")
        except Exception as exc:
            self.report_error(exc)

    def restore_defaults(self):
        self.fill_form(Settings())
        self.settings_feedback.setText("已载入默认参数，点击保存并应用后生效。已保存方案保留。")

    def undo_settings(self):
        try:
            if self.previous_settings is None:
                return
            self.commit_settings(self.previous_settings, remember=False)
            self.previous_settings = None
            self.fill_form(self.settings)
            self.runtime.log("已撤销上次参数应用。")
            self.settings_feedback.setText("已恢复并保存上一次应用前的参数。")
        except Exception as exc:
            self.report_error(exc)

    def tick(self):
        if self.closing:
            if not self.runtime.thread.is_alive():
                self.close()
            return
        if self.api:
            pressed = {key: bool(self.api.GetAsyncKeyState(key) & 0x8000) for key in self.key_down}
            rising = {key for key in pressed if pressed[key] and not self.key_down[key]}
            self.key_down = pressed
            if not self.settings.right_click_hotkey:
                rising.discard(2)
            if not self.settings.caps_lock_hotkey:
                rising.discard(20)
            if 119 in rising:
                self.runtime.set_active(False, "F8")
                self.next_render_at = 0.
            elif rising.intersection({2, 20}) and self.runtime.snapshot()["connected"] and not self.runtime.snapshot()["preview_enabled"]:
                # Avoid right-clicking a settings field accidentally arming output.
                if QApplication.activeWindow() is None:
                    self.toggle_active("鼠标右键" if 2 in rising else "Caps Lock")
        now = time.monotonic()
        if now >= self.next_render_at:
            self.render()
            self.next_render_at = now + .1

    @staticmethod
    def _text(widget, text):
        if widget.text() != text:
            widget.setText(text)

    @staticmethod
    def _enabled(widget, enabled):
        if widget.isEnabled() != enabled:
            widget.setEnabled(enabled)

    @staticmethod
    def _checked(widget, checked):
        if widget.isChecked() != checked:
            widget.setChecked(checked)

    def render(self):
        state = self.runtime.snapshot()
        active, connected, busy = state["active"], state["connected"], state["busy"]
        preview_enabled = state["preview_enabled"]
        running = active or preview_enabled
        if state["notice"] != self.last_notice:
            self.last_notice = state["notice"]
            if self.settings.sound_enabled:
                QApplication.beep()
        for name, enabled in (("鼠标右键", self.settings.right_click_hotkey), ("Caps Lock", self.settings.caps_lock_hotkey)):
            self._text(self.hotkey_labels[name], name + ("\n按下切换" if enabled else "\n已禁用"))
        statuses = {"idle": "已关闭", "loading": "加载模型", "waiting_window": "等待窗口",
                    "running": "正在识别", "preview": "仅识别预览", "model_error": "模型错误",
                    "capture_error": "截图错误", "window_error": "窗口已关闭", "device_error": "设备异常",
                    "waiting_bluetooth": "等待蓝牙", "connecting": "连接设备"}
        self._text(self.power_label, statuses.get(state["status"], "已关闭"))
        self._text(self.power, "关闭辅助" if active else "开启辅助")
        self._enabled(self.power, active or (connected and not busy and not preview_enabled and state["ble_connected"] is not False))
        self._text(self.preview_button, "停止预览" if preview_enabled else "仅识别预览")
        self._enabled(self.preview_button, not active and not busy)
        self._text(self.connect_button, "处理中…" if busy else "断开连接" if connected else "连接设备")
        self._enabled(self.connect_button, not busy)
        self._enabled(self.port, not connected and not busy)
        self._enabled(self.refresh_button, not connected and not busy)
        device_text = "设备未连接 · USB 串口发送指令，蓝牙 HID 返回位移"
        if connected:
            device_text = "旧版方向固件 · 蓝牙配对状态请在 Windows 中确认"
            if state["protocol"] == "xy1":
                device_text = "XY 双轴可变位移 · " + ("蓝牙已连接" if state["ble_connected"] else "等待蓝牙连接")
        self._text(self.device_status, device_text)
        if state["message"] != self.last_message:
            self._text(self.detail, state["message"])
            self.last_message = state["message"]
        for control in [*self.controls, self.window, self.window_refresh, *self.rate_buttons]:
            self._enabled(control, not running and not busy)
        self.update_cpu_threads_control()
        self._enabled(self.undo_button, not running and not busy and self.previous_settings is not None)
        for item, rate in zip(self.rate_buttons, (30, 60, 120)):
            self._checked(item, rate == self.settings.rate)
        preview = state["preview"]
        if preview is not None:
            size = (self.preview.width(), self.preview.height())
            if preview is not self.last_image or size != self.last_preview_size:
                h, w = preview.shape[:2]
                image = QImage(preview.data, w, h, preview.strides[0], QImage.Format.Format_RGB888).copy()
                self.preview.setPixmap(QPixmap.fromImage(image).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.last_image = preview
                self.last_preview_size = size
        else:
            self.last_image = None
            self._text(self.preview, "＋\n\n等待目标窗口画面" if running else "＋\n\n选择窗口后可仅识别预览")
        metrics = state["metrics"]
        for key, widget in self.metric_labels.items():
            value = metrics[key]
            visible = running and preview is not None and value is not None
            if key in ("serial", "ack"):
                visible = visible and active and metrics["moves"] > 0
            self._text(widget, f"{value:.1f}" if visible else "—")
        if running and preview is not None:
            self._text(self.stages_note, f"预处理 {metrics['preprocess']:.1f} · 后处理 {metrics['postprocess']:.1f} · "
                       f"目标筛选 {metrics['selection']:.1f} ms\n等待发送 {metrics['send_wait']:.1f} ms（最新一次写入）")
            age_text = f"{metrics['age']:.1f} ms" if metrics["moves"] else "—"
            self._text(self.latency_note, f"画面处理耗时（最近 120 帧）中位 {metrics['latency_p50']:.1f} / P95 {metrics['latency_p95']:.1f} ms"
                                     f"\n写入时画面年龄 {age_text} · 电脑端过期 {metrics['expired']} 帧 · 有效期 {self.settings.result_max_age_ms} ms")
        else:
            self._text(self.stages_note, "分阶段耗时：预处理 / 模型推理 / 后处理 / 目标筛选 / 等待发送。")
            self._text(self.latency_note, "画面处理耗时统计从开始截图到目标筛选完成；开启辅助或预览后更新。")
        output = f"串口写入 {metrics['moves']} 条"
        if state["protocol"] == "xy1" or metrics["xy1_output"]:
            output += (f" · 固件接受 {metrics['accepted']} 条 · 拒绝 {metrics['rejected']} 条"
                       f"（过期 {metrics['rejected_expired']} · 忙碌 {metrics['rejected_busy']}）")
            unconfirmed = metrics["moves"] - metrics["accepted"] - metrics["rejected"]
            if unconfirmed:
                output += f" · 未确认 {unconfirmed} 条"
            if metrics["ack_timeouts"]:
                output += f"（回执超时 {metrics['ack_timeouts']}）"
        if not running and (metrics["moves"] or metrics["expired"]):
            output = f"上次运行 · {output} · 电脑端过期 {metrics['expired']} 帧"
        self._text(self.output_note, output)
        self.output_note.setVisible(active or bool(metrics["moves"] or metrics["expired"]))
        if self.last_logs != state["logs"]:
            self.last_logs = state["logs"]
            self.log_list.clear()
            self.log_list.addItems(state["logs"])
        self._text(self.preview_note, f"窗口中心 {self.settings.crop_size} × {self.settings.crop_size} · 上限 {self.settings.rate} 次 / 秒")
        self._text(self.footer, f"{Path(self.settings.model).name}  ·  {self.settings.provider.replace('ExecutionProvider', '')}    |    检测 {metrics['targets']} 个    |    F8 停止辅助与预览")

    def closeEvent(self, event):
        if self.runtime.thread.is_alive():
            self.closing = True
            self.runtime.shutdown()
            self.setEnabled(False)
            self.setWindowTitle("准星助手 · 正在释放设备…")
            event.ignore()
        else:
            self.timer.stop()
            event.accept()


def main():
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()
