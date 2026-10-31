"""渲染冒烟：固定键帽 Dock 动画各帧导出 PNG，供人工观感确认（D-034）。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication
from ui.dock_strip import DockStrip

OUT = Path(__file__).resolve().parent.parent / "debug" / "_smoke_caps"
OUT.mkdir(parents=True, exist_ok=True)

ITEMS = ["b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j",
         "q", "x", "zh", "ch", "sh", "r", "z", "c", "s", "y", "w", ""]

app = QApplication([])
dock = DockStrip()
dock.update_content(ITEMS, 0)
dock.show()

# 声母层：焦点 0 → 3 的过渡帧 + 远端静止帧；再切窄层（韵母）
for f in (0.0, 0.35, 0.7, 1.0, 1.5, 2.0, 2.6, 3.0):
    dock._anim.stop()
    dock.set_focus(f)
    dock.repaint()
    dock.grab().save(str(OUT / f"sm_f{f:.2f}.png"))

dock.update_content(["a", "o", "ai", "ao", "an", "ang"], 2)
dock._anim.stop()
dock.set_focus(2.5)          # 过渡帧（两项此消彼长）
dock.repaint()
dock.grab().save(str(OUT / "sm_finals_f2.5.png"))
dock.set_focus(0.0)
dock.repaint()
dock.grab().save(str(OUT / "sm_finals_f0.png"))
print("saved:", OUT)
