"""ui/backdrop.py —— 背景采样器（D-042/D-044）：后台线程 GDI 区域捕获 + 逐级减半模糊

- **后台线程捕获**（D-044，根治卡顿）：旧版主线程 QScreen.grabWindow(0)
  = 整屏回读 + affinity 切换 → 主线程阻塞十几毫秒（界面一卡一卡）。
  新版 = 常驻 worker 线程 + GDI BitBlt **只拷窗口小区域**：
  ① 主线程零阻塞；② GDI 不采集分层窗口（本窗 WA_TranslucentBackground
  即分层）→ 天然排除自身，**无需 affinity 切换**（spike 实测品红 0.0%，
  spikes/spike_gdi_affinity.py）；③ 负坐标副屏物理坐标正常。
- **逐级减半模糊**（D-044，去像素感）：/2 连续降采样至 ~10px 再一次平滑
  回升——近似高斯，无单次 1/3 往返的块状像素感。
- 消费：透明皮肤的键帽/外框以透镜放大绘制（真实折射源）。
- offscreen / 非 Windows 安全降级（pix=None，绘制侧跳过）。
"""
import ctypes
import queue
import sys
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap


def _gdi_capture_bgrx(x: int, y: int, w: int, h: int):
    """GDI BitBlt 区域拷贝 → BGRA 字节串（物理像素；不采集分层窗口）。"""
    gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
    hdc = user.GetDC(None)
    try:
        mem = gdi.CreateCompatibleDC(hdc)
        try:
            bmp = gdi.CreateCompatibleBitmap(hdc, w, h)
            try:
                old = gdi.SelectObject(mem, bmp)
                try:
                    if not gdi.BitBlt(mem, 0, 0, w, h, hdc, x, y, 0x00CC0020):
                        return None
                    buf = ctypes.create_string_buffer(w * h * 4)

                    class BMIH(ctypes.Structure):
                        _fields_ = [("biSize", ctypes.c_uint32),
                                    ("biWidth", ctypes.c_int32),
                                    ("biHeight", ctypes.c_int32),
                                    ("biPlanes", ctypes.c_uint16),
                                    ("biBitCount", ctypes.c_uint16),
                                    ("biCompression", ctypes.c_uint32),
                                    ("biSizeImage", ctypes.c_uint32),
                                    ("biXPels", ctypes.c_int32),
                                    ("biYPels", ctypes.c_int32),
                                    ("biClrUsed", ctypes.c_uint32),
                                    ("biClrImportant", ctypes.c_uint32)]

                    bmi = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0,
                               0, 0, 0)
                    if not gdi.GetDIBits(mem, bmp, 0, h, buf,
                                         ctypes.byref(bmi), 0):
                        return None
                    return buf.raw
                finally:
                    gdi.SelectObject(mem, old)
            finally:
                gdi.DeleteObject(bmp)
        finally:
            gdi.DeleteDC(mem)
    finally:
        user.ReleaseDC(None, hdc)


def _progressive_blur(img: QImage) -> QImage:
    """磨砂阈值（D-046）：逐级减半至短边 ~20px + 一次平滑回升。
    20px = **文字不可读阈值**——背景里 14px 级别的文字缩到 ~2px 高，
    白色文字不再透出成"幽灵字/拖影"（用户截屏：聊天文字透过玻璃可读、
    键帽字母旁现重影）；大色块/形状仍可辨 = 磨砂玻璃。
    历史配位：64px（文字可读 → 幽灵字）← 现在 20px；10px 曾配全不透明
    = 实心板（错在透明度非模糊强度）。"""
    w, h = img.width(), img.height()
    small = img
    while min(small.width(), small.height()) > 20:
        small = small.scaled(max(1, small.width() // 2),
                             max(1, small.height() // 2),
                             Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def capture_rect(geo, dpr: float) -> tuple[int, int, int, int]:
    """D-048 坐标修复：**全局虚拟屏物理坐标**（GDI GetDC(None) 的坐标系，
    主屏左上为原点）。旧实现用 screen-local（geo − screen.geometry()），
    副屏上偏移整块屏 → 采到别的屏幕的内容（D-047 取证 B/C 实锤）。"""
    return (int(round(geo.x() * dpr)), int(round(geo.y() * dpr)),
            int(round(geo.width() * dpr)), int(round(geo.height() * dpr)))


class BackdropSampler(QObject):
    captured = Signal(QImage)     # 物理像素模糊背景（worker 线程产出）

    def __init__(self, window, interval_ms=200, enabled_fn=None):
        super().__init__(window)
        self._win = window
        self._enabled_fn = enabled_fn or (lambda: True)
        self.pix = None            # QPixmap（主线程转换后；物理像素无 DPR 元数据）
        self.dpr = 1.0
        self.last_latency_ms = None   # D-048 性能巡检：采样→产出延迟
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)
        self._queue: queue.Queue = queue.Queue(maxsize=1)
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker_started = False

    # ---------- 主线程 ----------

    def start(self) -> None:
        if sys.platform == "win32":
            if not self._worker_started:
                self._worker.start()
                self._worker_started = True
        self._tick()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def queue_depth(self) -> int:
        """D-048 性能巡检：积压深度（>0 = worker 跟不上）。"""
        return self._queue.qsize()

    def _tick(self) -> None:
        if not self._enabled_fn() or not self._win.isVisible():
            self._timer.start()         # 保持链（隐藏时静默轮询）
            return
        win = self._win
        handle = win.windowHandle()
        if handle is None or handle.screen() is None:
            self._timer.start()
            return
        self.dpr = handle.screen().devicePixelRatio() or 1.0
        x, y, w, h = capture_rect(win.frameGeometry(), self.dpr)
        if w <= 0 or h <= 0:
            self._timer.start()
            return
        try:                        # worker 忙时丢弃本轮（保底帧率，不积压）
            self._queue.put_nowait((x, y, w, h, int(win.winId())))
        except queue.Full:
            pass
        self._timer.start()         # 单发链：上一轮完成后再排下一轮

    def _work(self) -> None:
        """worker 线程：affinity 自排除 → GDI 拷贝 → 模糊（QImage 线程安全；
        跨线程信号自动排队）。**自排除 = SetWindowDisplayAffinity(
        WDA_EXCLUDEFROMCAPTURE) 捕获前置位、抓完复位**——spike 实证
        （spikes/spike_self_exclude.py）：非分层透明窗（本窗形态）GDI 采集率
        76.5%（= 拖影的自反馈根因），affinity 瞬时切换后 0.0%，开销 ~7ms
        在 worker 线程；微透明方案（opacity 0.9999）无效。
        异常必须捕获——线程内未处理异常会静默杀线程（D-044 教训）。"""
        import time as _time
        user32 = ctypes.windll.user32
        while True:
            x, y, w, h, hwnd = self._queue.get()
            t0 = _time.perf_counter()
            try:
                excluded = bool(user32.SetWindowDisplayAffinity(hwnd, 0x11))
                try:
                    raw = _gdi_capture_bgrx(x, y, w, h)
                finally:
                    if excluded:
                        user32.SetWindowDisplayAffinity(hwnd, 0)
                if raw is None:
                    continue
                # GDI 缓冲 = B,G,R,A 字节序 = 小端 0xAARRGGBB —— 与
                # Format_RGB32 布局一致且忽略 alpha 垃圾值（本 PySide6 版本
                # 无 Format_BGRX8888 枚举，教训见 D-044）
                img = QImage(raw, w, h, w * 4, QImage.Format.Format_RGB32)
                img = _progressive_blur(img.copy())   # copy 脱离 raw 缓冲
                self.last_latency_ms = (_time.perf_counter() - t0) * 1000
                self.captured.emit(img)
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
