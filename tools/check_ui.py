"""Render real Qt pages without connecting hardware; save visual QA artifacts."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Keep smoke runs separate from a user's persistent settings/logs.
os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="aim-ui-check-")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from aim_assist.ui import MainWindow, STYLE

app = QApplication([])
# Qt's offscreen platform does not enumerate the Windows system font database.
for font in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font))
app.setStyle("Fusion")
app.setStyleSheet(STYLE)
window = MainWindow()
window.timer.stop()  # This verification must not react to global hotkeys.
window.show()
output = Path(__file__).resolve().parent.parent / "artifacts"
output.mkdir(exist_ok=True)
try:
    for index, name in enumerate(("console", "settings", "logs")):
        window.navigate(index)
        for _ in range(4):
            app.processEvents()
        assert window.grab().save(str(output / f"{name}.png"))
        if index < 2:
            scroll = window.pages.widget(index).verticalScrollBar()
            scroll.setValue(scroll.maximum())
            app.processEvents()
            assert window.grab().save(str(output / f"{name}-bottom.png"))
            scroll.setValue(0)
    window.navigate(0)
    window.resize(1120, 1120)
    app.processEvents()
    assert window.grab().save(str(output / "console-full.png"))
    window.resize(940, 720)
    app.processEvents()
    assert window.grab().save(str(output / "console-small.png"))
    assert not window.runtime.snapshot()["connected"]
    print(f"UI rendered: {output}")
finally:
    window.runtime.shutdown()
    window.runtime.thread.join(3)
    window.close()
