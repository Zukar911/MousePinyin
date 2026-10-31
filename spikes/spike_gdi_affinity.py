"""spike：GDI BitBlt 区域捕获 + affinity 排除自身（D-044 决策依据）

目的：把背景采样从主线程 grabWindow（整屏回读，卡顿来源）换成
后台线程 GDI BitBlt 只拷窗口小区域。须验证：
  1. affinity=EXCLUDEFROMCAPTURE 对 GDI BitBlt 同样生效（品红 ~0%）
  2. 捕获的是真实桌面内容（非纯黑/纯色）
  3. 负坐标副屏物理坐标正确
"""
import ctypes
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

WDA_EXCLUDEFROMCAPTURE = 0x11


class BMIH(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPels", ctypes.c_int32), ("biYPels", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


def gdi_capture(x, y, w, h):
    gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
    hdc = user.GetDC(None)
    mem = gdi.CreateCompatibleDC(hdc)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
    old = gdi.SelectObject(mem, bmp)
    gdi.BitBlt(mem, 0, 0, w, h, hdc, x, y, 0x00CC0020)
    gdi.SelectObject(mem, old)
    bmi = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    user.ReleaseDC(None, hdc)
    return buf.raw  # BGRA 自底向上（biHeight 负 = 顶向下）


def stats(buf, w, h):
    magenta = dark = varied = 0
    total = 0
    colors = set()
    for yy in range(0, h, 3):
        row = yy * w * 4
        for xx in range(0, w, 3):
            o = row + xx * 4
            b_, g_, r_ = buf[o], buf[o + 1], buf[o + 2]
            total += 1
            if r_ > 200 and b_ > 200 and g_ < 80:
                magenta += 1
            if r_ < 25 and g_ < 25 and b_ < 25:
                dark += 1
            if len(colors) < 5000:
                colors.add((r_, g_, b_))
    return magenta / total, dark / total, len(colors)


def main() -> int:
    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    win.setAttribute(Qt.WA_TranslucentBackground)
    win.setStyleSheet("background: magenta;")
    win.setFixedSize(300, 120)
    placed = False
    for s in app.screens():
        if s.geometry().x() < -1000:
            win.move(s.geometry().x() + 100, s.geometry().y() + 100)
            placed = True
            break
    if not placed:
        win.move(100, 100)
    win.show()
    for _ in range(6):
        app.processEvents()
    geo = win.frameGeometry()
    hwnd = int(win.winId())
    print(f"位置 {geo.x()},{geo.y()} 尺寸 {geo.width()}x{geo.height()}")

    # 1) 不开 affinity：应看到大量品红（对照组）
    buf = gdi_capture(geo.x(), geo.y(), geo.width(), geo.height())
    m, d, v = stats(buf, geo.width(), geo.height())
    print(f"无 affinity：品红 {m*100:.1f}% 暗 {d*100:.1f}% 颜色数 {v}")

    # 2) 开 affinity：品红应 ~0（排除生效）
    ok = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    for _ in range(4):
        app.processEvents()
    buf = gdi_capture(geo.x(), geo.y(), geo.width(), geo.height())
    m, d, v = stats(buf, geo.width(), geo.height())
    print(f"affinity({ok})：品红 {m*100:.1f}% 暗 {d*100:.1f}% 颜色数 {v}")
    ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0)
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
