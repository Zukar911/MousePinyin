"""spike：背景采样捕获方案验证（D-042 决策依据）

问题：要把 Dock 窗口后方的屏幕画面作为玻璃折射源，必须捕获时**排除自身**
（否则自己的键帽模糊后出现在玻璃里 = 反馈回路）。
候选方案（真机实测，按优先级）：
  A. SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE=0x11) +
     QScreen.grabWindow(0) —— DWM 级排除，无闪烁（Win10 1903+）
  B. GDI BitBlt（不带 CAPTUREBLT）—— 旧技巧，分层窗口可能被排除
  C. setWindowOpacity(0) 闪隐捕获 —— 兜底（有闪烁，低频使用）

输出：每个方案捕获区域中"品红测试窗颜色"的像素占比（0% = 自身被排除 ✓）
另验证：负坐标副屏（用户 Dock 实际位置）捕获是否正常。
"""
import ctypes
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget

OUT = Path(__file__).resolve().parent / "_spike_backdrop"
OUT.mkdir(exist_ok=True)

WDA_EXCLUDEFROMCAPTURE = 0x11


def magenta_ratio(img) -> float:
    total = img.width() * img.height()
    hits = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            c = img.pixel(x, y)
            r, g, b = c >> 16 & 0xFF, c >> 8 & 0xFF, c & 0xFF
            if r > 200 and b > 200 and g < 80:
                hits += 1
    return hits / (total / 4)


def main() -> int:
    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
    win.setAttribute(Qt.WA_TranslucentBackground)
    win.setWindowOpacity(0.999)          # 半透明 → Qt 使用分层窗口
    win.setStyleSheet("background: magenta;")
    win.setFixedSize(300, 120)

    # 用户副屏（负 x）位置
    for s in app.screens():
        if s.geometry().x() < -1000:
            win.move(s.geometry().x() + 100, s.geometry().y() + 100)
            break
    else:
        win.move(100, 100)
    win.show()
    app.processEvents()
    app.processEvents()
    geo = win.frameGeometry()
    dpr = win.windowHandle().screen().devicePixelRatio() or 1.0
    print(f"测试窗位置 {geo.x()},{geo.y()} 尺寸 {geo.width()}x{geo.height()} dpr={dpr}")

    screen = win.windowHandle().screen()

    # ---- 方案 A：WDA_EXCLUDEFROMCAPTURE + grabWindow ----
    hwnd = int(win.winId())
    ok = ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    print(f"A. SetWindowDisplayAffinity(0x11) 返回 {ok}")
    app.processEvents()
    full = screen.grabWindow(0)
    img = full.toImage().copy(
        int((geo.x() - screen.geometry().x()) * dpr),
        int((geo.y() - screen.geometry().y()) * dpr),
        int(geo.width() * dpr), int(geo.height() * dpr))
    img.save(str(OUT / "A_affinity.png"))
    print(f"A. grabWindow 品红占比 = {magenta_ratio(img) * 100:.1f}% "
          f"（<1% = 排除成功，无闪烁 ✓）")
    ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0)

    # ---- 方案 B：GDI BitBlt（无 CAPTUREBLT）----
    gdi = ctypes.windll.gdi32
    user = ctypes.windll.user32
    hdc = user.GetDC(None)
    mem = gdi.CreateCompatibleDC(hdc)
    w, h = int(geo.width() * dpr), int(geo.height() * dpr)
    bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
    old = gdi.SelectObject(mem, bmp)
    user.SetProcessDPIAware()  # GDI 物理像素坐标
    ret = gdi.BitBlt(mem, 0, 0, w, h, hdc,
                     int(geo.x() * dpr), int(geo.y() * dpr), 0x00CC0020)
    gdi.SelectObject(mem, old)
    # 读回：GetDIBits 简化 — 用 Qt 再 grab 一次对照不可行，直接读位图位
    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPels", ctypes.c_int32),
                    ("biYPels", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]
    bmi = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(mem)
    user.ReleaseDC(None, hdc)
    hits = 0
    total = 0
    for y in range(0, h, 2):
        row = y * w * 4
        for x in range(0, w, 2):
            o = row + x * 4
            b_, g_, r_ = buf[o], buf[o + 1], buf[o + 2]
            total += 1
            if r_ > 200 and b_ > 200 and g_ < 80:
                hits += 1
    print(f"B. GDI BitBlt(无CAPTUREBLT) BitBlt返回 {ret} 品红占比 = "
          f"{hits / max(1, total) * 100:.1f}%")

    # ---- 方案 C：闪隐（作为兜底参考）----
    win.setWindowOpacity(0.0)
    app.processEvents()
    full = screen.grabWindow(0)
    win.setWindowOpacity(0.999)
    app.processEvents()
    img = full.toImage().copy(
        int((geo.x() - screen.geometry().x()) * dpr),
        int((geo.y() - screen.geometry().y()) * dpr),
        int(geo.width() * dpr), int(geo.height() * dpr))
    img.save(str(OUT / "C_flash.png"))
    print(f"C. 闪隐捕获品红占比 = {magenta_ratio(img) * 100:.1f}%（应 0%，但有闪烁）")

    win.close()
    print("结论落盘:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
