"""纯观察脚本（不改产品代码）：D-042 采样越界与拖影现象取证。

输出四张图到 debug/_observe/：
  A_user_view.png      用户所见（Qt grabWindow 整屏，含 Dock——DWM 合成路径）
  B_gdi_sampled.png    玻璃实际采到的内容（GDI BitBlt，复刻产品坐标换算——
                       含疑似 bug：screen-local 坐标而非全局坐标）
  C_gdi_correct.png    正确坐标（全局虚拟屏物理坐标）应采到的内容
  D_frame_crop.png     A 中 Dock 区域放大（拖影/越界观察）
另打印 Dock 窗口实测矩形与配置。
"""
import ctypes
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "_observe"
OUT.mkdir(exist_ok=True)

WDA = 0x11


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
    """GDI BitBlt（SRCCOPY 无 CAPTUREBLT）：排除分层窗口（= 排除 Dock）。"""
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
    img = QImage(buf.raw, w, h, w * 4, QImage.Format.Format_RGB32).copy()
    return img


def find_dock_rect():
    """按进程匹配：pythonw demo_main 的可见 Tool 窗口（尺寸范围）。"""
    import subprocess
    user = ctypes.windll.user32
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
         "Where-Object {$_.CommandLine -like '*demo_main*'} | "
         "Select-Object -ExpandProperty ProcessId) -join ','"],
        capture_output=True, text=True).stdout.strip()
    pids = {int(p) for p in out.split(",") if p.strip()}
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if not user.IsWindowVisible(hwnd):
            return True
        pid = ctypes.c_uint32()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        r = ctypes.wintypes.RECT()
        user.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if 800 <= w <= 2200 and 60 <= h <= 260:
            found.append((r.left, r.top, w, h))
        return True

    user.EnumWindows(cb, None)
    return found


def main() -> int:
    import ctypes.wintypes
    app = QApplication(sys.argv)
    cfg = json.loads((ROOT / "data" / "config.json").read_text(encoding="utf-8"))
    print("配置:", {k: cfg[k] for k in ("skin", "backdrop", "x", "y")})

    docks = find_dock_rect()
    print("找到 Dock 窗口:", docks)
    if not docks:
        print("!! 未找到 Dock 窗口（demo 未运行或不在预期尺寸范围）")
        return 1
    dx, dy, dw, dh = docks[0]

    # 包含 Dock 的屏幕
    screens = app.screens()
    target = None
    for s in screens:
        if s.geometry().contains(dx + dw // 2, dy + dh // 2):
            target = s
            break
    target = target or app.primaryScreen()
    sg = target.geometry()
    dpr = target.devicePixelRatio() or 1.0
    print(f"所在屏 {target.name()} geometry={sg.x()},{sg.y()} "
          f"{sg.width()}x{sg.height()} dpr={dpr}")

    # A. 用户所见：Qt grabWindow（DWM 合成，含 Dock）
    full = target.grabWindow(0)
    full.save(str(OUT / "A_user_view.png"))

    # 物理坐标裁剪 Dock 区域（放大 2× 便于观察）；grabWindow 为物理像素
    px, py = int(dx - sg.x() * dpr), int(dy - sg.y() * dpr)
    pw, ph = dw, dh
    crop = full.toImage().copy(px, py, pw, ph).scaled(
        pw * 2, ph * 2)
    crop.save(str(OUT / "D_frame_crop.png"))

    # B. 玻璃实际采样（D-048 修复后：产品 capture_rect，输入须为 Qt 逻辑坐标）
    from ui.backdrop import capture_rect as product_rect
    QtCore = __import__("PySide6.QtCore", fromlist=["QRect"])
    lx, ly, lw, lh = dx / dpr, dy / dpr, dw / dpr, dh / dpr
    bx, by, bw, bh = product_rect(QtCore.QRect(int(lx), int(ly),
                                               int(lw), int(lh)), dpr)
    img_b = gdi_capture(bx, by, bw, bh)
    img_b.save(str(OUT / "B_gdi_sampled.png"))

    # C. 正确采样（全局物理坐标）
    img_c = gdi_capture(int(dx * 1.0), int(dy * 1.0), dw, dh)
    img_c.save(str(OUT / "C_gdi_correct.png"))

    # 程序化判读：B 与 C 像素一致率（修复前 B 采到别的屏 ≈ 完全不同）
    if img_b.size() == img_c.size():
        diff = same = 0
        for yy in range(0, img_b.height(), 4):
            for xx in range(0, img_b.width(), 4):
                pb, pc = img_b.pixel(xx, yy), img_c.pixel(xx, yy)
                if abs((pb >> 16 & 255) - (pc >> 16 & 255)) <= 12:
                    same += 1
                diff += 1
        ratio = same / max(1, diff)
        verdict = "PASS 坐标已修复" if ratio > 0.9 else "FAIL 仍越界"
        print(f"B/C 一致率 {ratio*100:.1f}% → {verdict}")
    else:
        print(f"B{img_b.size()} 与 C{img_c.size()} 尺寸不等 → 检查换算")

    print("已保存 4 张取证图到", OUT)
    print("判读：B 与 C 差异大 → 采样坐标 bug（采到了别的屏）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
