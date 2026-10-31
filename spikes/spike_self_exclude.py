"""spike：非分层透明窗（WA_TranslucentBackground + opacity=1.0）的 GDI 自排除方案
（T-049/D-047 修复计划 ②，取证已证明此形态被 GDI 采集 = 拖影根因）

对照两方案：
  A. setWindowOpacity(0.9999) —— Qt 切换到分层合成路径 → GDI 永久排除（零逐帧开销）
  B. SetWindowDisplayAffinity 瞬时切换（worker 捕获前后置位/复位）
判据：品红占比（<1% = 排除成功）+ 渲染完好（窗口文字仍可见）。
"""
import ctypes
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


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
    return buf.raw


def magenta_ratio(buf, w, h):
    hits = total = 0
    for yy in range(0, h, 3):
        row = yy * w * 4
        for xx in range(0, w, 3):
            o = row + xx * 4
            b_, g_, r_ = buf[o], buf[o + 1], buf[o + 2]
            total += 1
            if r_ > 200 and b_ > 200 and g_ < 80:
                hits += 1
    return hits / max(1, total)


def main() -> int:
    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    win.setAttribute(Qt.WA_TranslucentBackground)          # 与真实 Dock 同形态
    lay = QVBoxLayout(win)
    lab = QLabel("TEST 12")
    lab.setStyleSheet("color: magenta; font-size: 30px; font-weight: bold;"
                      "background: magenta; border-radius: 8px;")
    lay.addWidget(lab)
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
    for _ in range(10):
        app.processEvents()

    g = win.frameGeometry()
    dpr = win.windowHandle().screen().devicePixelRatio() or 1.0
    px, py = int(g.x() * dpr), int(g.y() * dpr)
    pw, ph = int(g.width() * dpr), int(g.height() * dpr)

    buf = gdi_capture(px, py, pw, ph)
    print(f"opacity=1.0（真实 Dock 形态）：品红 {magenta_ratio(buf, pw, ph)*100:.1f}%"
          "（取证预期：高 = 被采集）")

    # 方案 A：微透明 → 分层合成路径
    win.setWindowOpacity(0.9999)
    for _ in range(10):
        app.processEvents()
    buf = gdi_capture(px, py, pw, ph)
    ratio_a = magenta_ratio(buf, pw, ph)
    # 用户所见渲染完好性（Qt 合成路径自查）
    qt_shot = win.grab()
    print(f"方案A opacity=0.9999：品红 {ratio_a*100:.1f}%（<1% = 排除成功）"
          f"；Qt 渲染 {qt_shot.width()}x{qt_shot.height()} 非空={not qt_shot.isNull()}")

    # 方案 B：affinity 瞬时切换（计时）
    win.setWindowOpacity(1.0)
    for _ in range(10):
        app.processEvents()
    hwnd = int(win.winId())
    user32 = ctypes.windll.user32
    t0 = time.perf_counter()
    user32.SetWindowDisplayAffinity(hwnd, 0x11)
    buf = gdi_capture(px, py, pw, ph)
    user32.SetWindowDisplayAffinity(hwnd, 0)
    dt = (time.perf_counter() - t0) * 1000
    ratio_b = magenta_ratio(buf, pw, ph)
    print(f"方案B affinity 瞬时切换：品红 {ratio_b*100:.1f}%；开销 {dt:.1f}ms")

    win.close()
    print("结论：A 永久排除且零开销" if ratio_a < 0.01 else
          "A 失效 → 用 B（每帧 2 次调用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
