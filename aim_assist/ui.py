"""Native adaptation of the supplied three-page Aim Assist UI prototype."""
from dataclasses import replace
import os
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
        self.last_image = None
        self.last_logs = None
        self.last_message = ""
        self.closing = False
        self.api = user32() if os.name == "nt" else None
        self.key_down = {key: bool(self.api.GetAsyncKeyState(key) & 0x8000) if self.api else False for key in (2, 20, 119)}
        self.controls = []
        self.build()
        self.refresh_devices()
        self.refresh_windows()
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
        transport.addItem("蓝牙 HID · w/a/s/d")
        transport.addItem("USB HID · 需匹配固件")
        transport.model().item(1).setEnabled(False)
        transport.setToolTip("当前已接入 Espressif BLE Mouse 固定步长协议。")
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
        self.detail = label("", "muted", True)
        self.detail.setMinimumHeight(36)
        left.addWidget(self.detail)
        left.addWidget(label("两个快捷键，同一个开关", "heading"))
        keys = QHBoxLayout()
        for text in ("鼠标右键\n按下切换", "Caps Lock\n按下切换"):
            key = label(text, "chip")
            key.setAlignment(Qt.AlignmentFlag.AlignCenter)
            keys.addWidget(key)
        left.addLayout(keys)
        left.addWidget(label("F8 随时关闭辅助", "muted"))
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
        stats = QHBoxLayout()
        self.metric_labels = []
        for title, note in (("实际识别频率", "次 / 秒"), ("单轮识别耗时", "ms · 预处理至目标筛选"), ("串口写入耗时", "ms · 不含 HID 到达时间")):
            column = QVBoxLayout()
            column.addWidget(label(title, "muted"))
            value = label("—", "value")
            self.metric_labels.append(value)
            column.addWidget(value)
            column.addWidget(label(note, "muted"))
            stats.addLayout(column, 1)
        metrics_box.addLayout(stats)
        metrics_box.addWidget(label("指令到达 Windows：未测量（当前固件无接收端回执）", "muted"))
        layout.addWidget(metrics)

    def build_settings(self):
        layout = self.page("参数设置", "辅助关闭后调整，点击保存应用。配置保存在本机。")
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
        layout.addWidget(model_card)
        parameters, box = card("辅助参数")
        grid = QGridLayout()
        self.inputs = {}
        specs = (("strength", "移动倍率", .05, 1., .05), ("confidence", "识别置信度", .1, .95, .05),
                 ("aim_height", "瞄准高度 · 从框顶部计，0.30 为上身", .05, .5, .01), ("deadzone", "死区 · 截图像素", 0, 100, 1),
                 ("radius", "选取半径 · 截图像素", 10, 640, 5), ("crop_size", "截图边长 · 像素", 160, 1280, 32),
                 ("max_step", "修正值上限 · 协议量化前", 1, 100, 1), ("mask_width", "遮罩宽度 · 像素", 0, 1280, 10),
                 ("mask_height", "遮罩高度 · 像素", 0, 1280, 10))
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
        box.addWidget(label("当前固件每条指令固定移动约 10 counts，最多 30 条 / 秒；倍率影响量化前修正值，不能改变固件步长。", "muted", True))
        layout.addWidget(parameters)
        self.save_button = button("保存并应用", self.apply_settings, "primary")
        self.settings_feedback = label("", "muted", True)
        layout.addWidget(self.settings_feedback)
        layout.addWidget(self.save_button)
        layout.addStretch()
        self.controls = [self.model_path, self.browse_button, self.provider, self.mask, self.mask_side, self.save_button, *self.inputs.values()]

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

    def set_rate(self, rate):
        try:
            updated = replace(self.settings, rate=rate)
            self.runtime.configure(updated, self.window.currentData() or 0)
            save_settings(updated)
            self.settings = updated
            self.runtime.log(f"识别频率上限：{rate} 次 / 秒")
        except Exception as exc:
            self.report_error(exc)

    def browse_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 YOLOv5 ONNX 模型", str(ROOT), "ONNX 模型 (*.onnx)")
        if path:
            self.model_path.setText(path)

    def apply_settings(self):
        try:
            path = Path(self.model_path.text()).expanduser().resolve()
            if not path.is_file() or path.suffix.lower() != ".onnx":
                raise ValueError("请选择存在的 .onnx 模型文件")
            updated = replace(self.settings, model=str(path), provider=self.provider.currentData(), port=self.port.currentData() or "",
                              mask=self.mask.isChecked(), mask_side=self.mask_side.currentData(), **{key: widget.value() for key, widget in self.inputs.items()}).validate()
            self.runtime.configure(updated, self.window.currentData() or 0)
            save_settings(updated)
            self.settings = updated
            self.runtime.log("参数已保存并应用；模型在下次开启时加载。")
            self.settings_feedback.setText("已保存。下次开启辅助时使用新参数。")
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
            if 119 in rising:
                self.runtime.set_active(False, "F8")
            elif rising.intersection({2, 20}) and self.runtime.snapshot()["connected"]:
                # Avoid right-clicking a settings field accidentally arming output.
                if QApplication.activeWindow() is None:
                    self.toggle_active("鼠标右键" if 2 in rising else "Caps Lock")
        self.render()

    def render(self):
        state = self.runtime.snapshot()
        active, connected, busy = state["active"], state["connected"], state["busy"]
        self.power_label.setText("已开启" if active else "已关闭")
        self.power.setText("关闭辅助" if active else "开启辅助")
        self.power.setEnabled(connected and not busy)
        self.connect_button.setText("连接中…" if busy else "断开连接" if connected else "连接设备")
        self.connect_button.setEnabled(not busy)
        self.port.setEnabled(not connected and not busy)
        self.refresh_button.setEnabled(not connected and not busy)
        self.device_status.setText("串口已打开 · 蓝牙配对状态请在 Windows 中确认" if connected else "设备未连接 · USB 串口发送指令，蓝牙 HID 返回位移")
        if state["message"] != self.last_message:
            self.detail.setText(state["message"])
            self.last_message = state["message"]
        for control in [*self.controls, self.window, self.window_refresh, *self.rate_buttons]:
            control.setEnabled(not active and not busy)
        for item, rate in zip(self.rate_buttons, (30, 60, 120)):
            item.setChecked(rate == self.settings.rate)
        preview = state["preview"]
        if preview is not None:
            if preview is not self.last_image:
                h, w = preview.shape[:2]
                image = QImage(preview.data, w, h, preview.strides[0], QImage.Format.Format_RGB888).copy()
                self.preview.setPixmap(QPixmap.fromImage(image).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.last_image = preview
        else:
            self.last_image = None
            self.preview.setText("＋\n\n等待目标窗口画面" if active else "＋\n\n辅助关闭 · 预览暂停")
        metrics = state["metrics"]
        for widget, key in zip(self.metric_labels, ("fps", "inference", "serial")):
            widget.setText(f"{metrics[key]:.1f}" if active and preview is not None else "—")
        if self.last_logs != state["logs"]:
            self.last_logs = state["logs"]
            self.log_list.clear()
            self.log_list.addItems(state["logs"])
        self.preview_note.setText(f"窗口中心 {self.settings.crop_size} × {self.settings.crop_size} · 上限 {self.settings.rate} 次 / 秒")
        self.footer.setText(f"{Path(self.settings.model).name}  ·  {self.settings.provider.replace('ExecutionProvider', '')}    |    检测 {metrics['targets']} 个 · 已发送 {metrics['moves']} 条    |    F8 关闭辅助")

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
