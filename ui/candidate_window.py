"""ui/candidate_window.py —— 外框式悬浮键帽 Dock（D-020~D-028）

形态：**可见玻璃外框**（D-028 用户方案）——圆角细边框，框内为本程序操作区；
⠿ 拖动把手位于**外框上边正中央**，以把手下方为窗口锚点：所有缩放/层切换
以**顶边中心**为锚（水平中心+顶边 y 钉死不动，宽度向两侧伸缩），根治乱跳。
无边框窗口本体、置顶、不抢焦点、不进任务栏。

交互（F-001 合规，D-032：选中只由滚轮决定）：
  滚轮 = 移动选中项（delta 累积，灵敏度可调 wheel_sens）
  左键点选中键 / 空白处 = 确认（confirm_requested）
  左键点未选中键 = 忽略（不移焦点/不确认/不发键，Dock 层吞掉）
  hover 无任何视觉反馈（颜色/大小/描边/光标均不变）
  右键 = 切选字  X1 = 切模式  X2 = 退格撤销
  ⠿ 按住 = 拖动窗口  ⚙ = 设置  ✕ = 退出（Ctrl+Alt+Q）
"""

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import (QApplication, QToolButton, QVBoxLayout, QWidget)

from core.events import Event
from ui.backdrop import BackdropSampler
from ui.dock_strip import DockStrip
from ui.settings_dialog import SettingsDialog
from ui.theme import Config, load_config, save_config

GRIP_H = 20        # 顶部把手条高度
MARGIN = 4         # 外框内边距


def btn_css(fg: str) -> str:
    # 注意：第 2/3 段是普通字符串，"}}" 是字面双括号 → QSS 解析失败整表被弃
    # （真机 ⚙/✕/⠿ 全部回退系统默认样式），每条规则必须恰好一个 "}" 闭合
    return (
        f"QToolButton{{background:rgba(120,130,160,60);color:{fg};"
        "border:1px solid rgba(160,170,200,90);border-radius:13px;font-size:13px;}"
        "QToolButton:hover{background:rgba(140,150,190,120);color:white;}"
    )


class CandidateWindow(QWidget):
    def __init__(self, event_hook=None, jump_hook=None, on_cap_click=None,
                 on_debug=None, global_mode=False):
        super().__init__()
        self.event_hook = event_hook
        self.jump_hook = jump_hook
        self.on_cap_click = on_cap_click
        self.on_debug = on_debug          # D-030 调试旁路：原始操作描述（不改行为）
        # T-014 P4 全局模式：鼠标事件由 io_source/pynput_source.py 全局钩子
        # 投递（本窗口 Qt 事件路径抑制，避免双份处理）；⚙/✕/⠿ 独立按钮不受影响
        self.global_mode = global_mode
        self.cfg: Config = load_config()
        self._settings_dlg: SettingsDialog | None = None
        self._wheel_acc = 0              # 滚轮 delta 累积器（D-028 修"一次跳两格"）

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.dock = DockStrip()
        self.dock.set_config(self.cfg)
        self.dock.on_debug = on_debug    # D-030：键帽点击旁路描述

        lay = QVBoxLayout(self)
        lay.setContentsMargins(MARGIN, GRIP_H, MARGIN, MARGIN)
        lay.setSpacing(0)
        lay.addWidget(self.dock)

        self.dock.confirm_requested.connect(self._on_cap)
        self.dock.size_changed.connect(self._resize_to_config)

        # ⚙ / ✕ 角标（行内右侧，pad_r 预留）
        fg = self.cfg.skin_obj.text
        self.btn_settings = QToolButton(self)
        self.btn_settings.setText("⚙")
        self.btn_settings.setToolTip("设置（皮肤/大小/玻璃/滚轮）")
        self.btn_settings.setStyleSheet(btn_css(fg))
        self.btn_settings.setFixedSize(26, 26)
        self.btn_settings.clicked.connect(self.open_settings)

        self.btn_close = QToolButton(self)
        self.btn_close.setText("✕")
        self.btn_close.setToolTip("退出（Ctrl+Alt+Q）")
        self.btn_close.setStyleSheet(btn_css(fg))
        self.btn_close.setFixedSize(26, 26)
        self.btn_close.clicked.connect(self.close)

        # ⠿ 拖动把手：外框上边正中央（D-028 用户方案）
        self.btn_move = QToolButton(self)
        self.btn_move.setText("⠿")
        self.btn_move.setToolTip("按住拖动窗口位置")
        self.btn_move.setStyleSheet(btn_css(fg))
        self.btn_move.setFixedSize(28, 18)
        self.btn_move.installEventFilter(self)   # 按住即拖（eventFilter）

        self._resize_to_config()
        self._restore_pos()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._save_pos)

        # D-041 光标光源：轮询全局光标（窗口不抢焦点、不需要鼠标进入），
        # 映射为本窗局部坐标注入 dock 与外框——照亮玻璃边缘（纯外观层，
        # 不影响任何交互语义；光标远离时衰减为不可见）
        self._light = None
        self._light_last = None
        self._light_timer = QTimer(self)
        self._light_timer.setInterval(16)
        self._light_timer.timeout.connect(self._poll_light)
        self._light_timer.start()

        # D-042/D-044 背景采样：透明皮肤（trans>0）时后台线程 GDI 捕获窗口
        # 后方画面作为玻璃折射源（分层窗口天然不被 GDI 采集 = 自动排除自身）
        self._backdrop_pix = None
        self._backdrop_dpr = 1.0
        self._sampler = BackdropSampler(
            self, enabled_fn=lambda: (self.cfg.backdrop
                                      and self.cfg.skin_obj.trans > 0.02))
        self._sampler.captured.connect(self._on_backdrop)

    # ---------- D-042/D-044 背景采样 ----------

    def _on_backdrop(self, img) -> None:
        """worker 线程产出 QImage（跨线程排队信号）→ 主线程转 QPixmap 分发。"""
        from PySide6.QtGui import QPixmap
        self._backdrop_pix = QPixmap.fromImage(img)
        self._backdrop_dpr = self._sampler.dpr
        self._sampler.pix = self._backdrop_pix
        self.dock._backdrop = self._backdrop_pix
        self.dock._backdrop_dpr = self._sampler.dpr
        self.dock._backdrop_off = QPointF(MARGIN, GRIP_H)
        self.dock.update()
        self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        self._sampler.start()        # GDI 不采集分层窗口：天然排除自身，无 affinity
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._sampler.stop()
        super().hideEvent(e)

    # ---------- 光标光源（D-038：仅外观） ----------

    def _poll_light(self) -> None:
        """16ms 轮询光标位置 → 本窗局部坐标；移动 ≥1px 才重绘（静止零开销）。"""
        if not self.isVisible():
            return
        from PySide6.QtGui import QCursor
        gp = QCursor.pos()
        if self._light_last is not None and gp == self._light_last:
            return
        self._light_last = gp
        lp = self.mapFromGlobal(gp)
        self._light = QPointF(lp)
        self.dock._light = self._light
        self.dock.update()
        self.update()

    # ---------- 外框绘制（D-028 可见方框 + D-038 光效） ----------

    def paintEvent(self, e) -> None:  # noqa: N802
        import math
        from PySide6.QtGui import QPainterPath
        from PySide6.QtCore import QRectF
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        skin = self.cfg.skin_obj
        tex = self.cfg.texture_obj
        glass = self.cfg.glass
        trans = skin.trans
        frame = QRectF(1, 1, self.width() - 2, self.height() - 2)
        # 底：透明皮肤 = **模糊背景**（真实折射源，D-042）+ 淡色调；非透明
        # 皮肤保持纯色淡底
        edge = QColor(skin.cap_border)
        edge.setAlpha(190)
        p.setPen(QPen(edge, 1.5))
        fill = QColor(skin.cap_bottom)
        if trans > 0.02 and self._backdrop_pix is not None:
            # D-045：外框底同样 80% 透明度轻磨砂（透出真实桌面 = 玻璃感）
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            d = self._backdrop_dpr
            p.setOpacity(0.80)
            p.drawPixmap(frame, self._backdrop_pix,
                         QRectF(frame.x() * d, frame.y() * d,
                                frame.width() * d, frame.height() * d))
            p.setOpacity(1.0)
            fill.setAlpha(int(46 * (1.0 - trans * 0.4)))
            p.setBrush(fill)
            p.drawRoundedRect(frame, 12, 12)
        else:
            fill.setAlpha(int((30 + 50 * glass) * (1.0 - trans * 0.9)))
            p.setBrush(fill)
            p.drawRoundedRect(frame, 12, 12)

        light = self._light
        if light is not None and tex.light_gain > 0.02:
            # D-044 光源照边（羽化）：双层径向（宽淡晕 + 窄亮核）替代单层
            lr = 170.0
            la = int(205 * min(tex.light_gain, 1.2))
            halo = QRadialGradient(light, lr * 1.6)
            halo.setColorAt(0.0, QColor(255, 244, 216, int(la * 0.30)))
            halo.setColorAt(0.55, QColor(255, 240, 200, int(la * 0.11)))
            halo.setColorAt(1.0, QColor(255, 240, 200, 0))
            p.setPen(QPen(QBrush(halo), 4.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(frame, 12, 12)
            lg = QRadialGradient(light, lr)
            lg.setColorAt(0.0, QColor(255, 248, 226, min(la, 230)))
            lg.setColorAt(0.42, QColor(255, 240, 200, int(la * 0.40)))
            lg.setColorAt(1.0, QColor(255, 240, 200, 0))
            p.setPen(QPen(QBrush(lg), 2.4))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(frame, 12, 12)
            # 炫光条：光标到最近边（上/下）的垂距越近越亮，横向渐隐
            cy = frame.center().y()
            if light.y() <= cy:
                gy = frame.y() + 1.2
            else:
                gy = frame.bottom() - 1.2
            gx_lo = frame.x() + 16
            gx_hi = frame.right() - 16
            gx = min(max(light.x(), gx_lo + 46), gx_hi - 46)
            dist_e = math.hypot(max(gx_lo - light.x(), 0.0,
                                    light.x() - gx_hi),
                                abs(light.y() - gy))
            gain_f = max(0.0, 1.0 - dist_e / 240.0) * min(tex.light_gain, 1.2)
            # D-043：背景折射在场时软化（线更短更淡——真实背景已提供质感）
            if trans > 0.02 and self._backdrop_pix is not None:
                gain_f *= 0.55
            if gain_f > 0.04:
                # D-044 炫光条羽化：三层渐变叠描（宽/中/窄 × 淡/中/亮）
                sa = int(185 * gain_f)
                for pen_w, ka in ((7.0, 0.15), (3.8, 0.42), (1.6, 1.0)):
                    streak = QLinearGradient(gx - 62, gy, gx + 62, gy)
                    streak.setColorAt(0.0, QColor(255, 250, 235, 0))
                    streak.setColorAt(0.5, QColor(255, 250, 235,
                                                  min(int(sa * ka), 240)))
                    streak.setColorAt(1.0, QColor(255, 250, 235, 0))
                    p.setPen(QPen(QBrush(streak), pen_w))
                    p.setBrush(Qt.NoBrush)
                    p.drawLine(QPointF(gx - 62, gy), QPointF(gx + 62, gy))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 252, min(int(sa * 0.85) + 40, 255)))
                p.drawEllipse(QPointF(gx, gy), 1.6, 1.6)
        if tex.dispersion > 0.05:
            # 色散（相差）：青/红双描边错位
            da = int(58 * tex.dispersion)
            off = 1.0 * tex.dispersion
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(80, 220, 255, da), 1.1))
            p.drawRoundedRect(frame.adjusted(-off, -off, off, off), 13, 13)
            p.setPen(QPen(QColor(255, 96, 96, da), 1.1))
            p.drawRoundedRect(frame.adjusted(off, off, -off, -off), 13, 13)
        if tex.refract > 0.05 and not (trans > 0.02
                                       and self._backdrop_pix is not None):
            # D-041/D-043 折射弧：非透明皮肤保留（横向渐变两端淡出）；
            # 透明皮肤有真实背景折射时**移除**（画出来的弧浮在背景上生硬）
            sag = 3.0 * tex.refract
            a = int(42 * tex.refract)
            gbr = QLinearGradient(frame.x(), 0, frame.right(), 0)
            gbr.setColorAt(0.0, QColor(255, 255, 255, 0))
            gbr.setColorAt(0.22, QColor(255, 255, 255, int(a * 0.55)))
            gbr.setColorAt(0.5, QColor(255, 255, 255, a))
            gbr.setColorAt(0.78, QColor(255, 255, 255, int(a * 0.5)))
            gbr.setColorAt(1.0, QColor(255, 255, 255, 0))
            path = QPainterPath(QPointF(frame.x() + 14, frame.y() + 5))
            path.quadTo(QPointF(frame.center().x(), frame.y() + 5 + sag),
                        QPointF(frame.right() - 14, frame.y() + 5))
            p.setPen(QPen(QBrush(gbr), 1.4))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.end()

    # ---------- 尺寸 / 位置 / 配置 ----------

    def _resize_to_config(self) -> None:
        """D-050 固定外框：窗口尺寸**跟随 Dock**（Dock 按容量包络定宽，
        层级切换不再触发窗口缩放）；本方法只做两件事——同步窗口尺寸、
        按锚点钳制把窗口保持在所在屏内（D-029 钳制逻辑保留）。"""
        from PySide6.QtCore import QPoint
        old_w, old_h = self.width(), self.height()
        w = self.dock.width() + MARGIN * 2
        h = self.dock.height() + GRIP_H + MARGIN * 2
        if w == old_w and h == old_h:
            self._place_buttons()
            return                              # 尺寸未变：不动（防抖）
        self.setFixedSize(w, h)
        self._place_buttons()
        if self.isVisible():
            anchor_x = self.x() + old_w // 2
            anchor_y = self.y()
            screens = QApplication.screens()
            geoms = [s.geometry() for s in screens]
            idx = self._screen_containing(QPoint(anchor_x, anchor_y), geoms)
            if idx < 0:
                idx = self._screen_containing(
                    QPoint(self.x() + old_w // 2, self.y() + old_h // 2), geoms)
            avail = (screens[idx].availableGeometry() if idx >= 0
                     else QApplication.primaryScreen().availableGeometry())
            nx, ny = self._anchor_clamp(anchor_x - w // 2, anchor_y, w, h,
                                        avail)
            self.move(nx, ny)

    @staticmethod
    def _screen_containing(pt, geoms) -> int:
        """返回包含点 pt（逻辑坐标）的屏幕 geometry 序号；无则 -1。"""
        for i, g in enumerate(geoms):
            if g.contains(pt):
                return i
        return -1

    @staticmethod
    def _anchor_clamp(nx: int, ny: int, w: int, h: int, avail) -> tuple[int, int]:
        """顶边中心锚点尽量保持（坐标可为负）；仅必要限制：
        窗口与目标屏可用区完全不相交 → 拉回屏内；
        吸底窗口底边超出下缘 → 上移贴底。"""
        if nx + w <= avail.left() or nx >= avail.right():
            nx = avail.left()                    # 完全水平出界才拉回
        if ny > avail.bottom() or ny + h <= avail.top():
            ny = avail.top()                     # 完全垂直出界才拉回
        elif ny + h > avail.bottom() + 1:
            ny = avail.bottom() + 1 - h          # 吸底部分出界：贴底
        return nx, ny

    def _place_buttons(self) -> None:
        W = self.width()
        gy = GRIP_H + (self.dock.height() // 2) - 13
        self.btn_close.move(W - 26 - 10, gy)            # ✕ 行内最右
        self.btn_settings.move(W - 26 - 10 - 30, gy)    # ⚙ 行内右二
        self.btn_move.move(W // 2 - 14, 1)              # ⠿ 顶边正中央

    def apply_config(self, cfg: Config) -> None:
        """设置界面实时回调：应用 + 落盘；尺寸变化由 size_changed 信号驱动。"""
        self.cfg = cfg
        save_config(cfg)
        if getattr(self, "on_config_changed", None) is not None:
            self.on_config_changed(cfg)     # D-049 三键开关等外部状态同步
        # D-043 背景采样开关：关闭或非透明皮肤 → 停采样并清空折射源（立即
        # 回落平涂）；重新打开 → 重启采样
        if cfg.backdrop and cfg.skin_obj.trans > 0.02:
            if self.isVisible():
                self._sampler.start()
        else:
            self._sampler.stop()
            self._backdrop_pix = None
            self.dock._backdrop = None
        self.dock.set_config(cfg)
        self.update()

    def _restore_pos(self) -> None:
        if self.cfg.x is not None and self.cfg.y is not None:
            self.move(self.cfg.x, self.cfg.y)
            return
        # 首次启动默认位：鼠标所在屏吸底居中（D-029：不固定主屏）
        from PySide6.QtGui import QCursor
        from PySide6.QtCore import QPoint
        pos = QCursor.pos()
        geoms = [s.geometry() for s in QApplication.screens()]
        idx = self._screen_containing(pos, geoms)
        scr = (QApplication.screens()[idx] if idx >= 0
               else QApplication.primaryScreen())
        geo = scr.availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.bottom() - self.height() - 6)

    def _save_pos(self) -> None:
        g = self.frameGeometry().topLeft()
        if self.cfg.x == g.x() and self.cfg.y == g.y():
            return
        self.cfg.x, self.cfg.y = g.x(), g.y()
        save_config(self.cfg)

    # ---------- 设置界面 ----------

    def open_settings(self) -> None:
        if self._settings_dlg is not None and self._settings_dlg.isVisible():
            self._settings_dlg.raise_()
            self._settings_dlg.activateWindow()
            return
        dlg = SettingsDialog(self, self.cfg, on_change=self.apply_config)
        dlg.show()                      # 非模态：设置时仍可试滚键帽
        self._settings_dlg = dlg

    # ---------- 确认 ----------

    def _on_cap(self, idx: int) -> None:
        if self.on_cap_click:
            self.on_cap_click(idx)

    # ---------- 拖动把手（⠿ 顶边中央，唯一拖动途径） ----------

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        from PySide6.QtCore import QEvent
        if obj is self.btn_move and ev.type() == QEvent.MouseButtonPress:
            if self.windowHandle() is not None:
                self.windowHandle().startSystemMove()   # OS 接管：按住即拖
            return True
        return super().eventFilter(obj, ev)

    # ---------- 调试旁路（D-030：仅描述原始操作，不改行为） ----------

    def _dbg(self, desc: str, instant: bool = False) -> None:
        if self.on_debug:
            self.on_debug(desc, instant)

    # ---------- 鼠标 / 滚轮（输入语义） ----------

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if self.global_mode:
            e.accept()          # T-014：事件由全局钩子投递，Qt 路径抑制
            return
        if e.button() in (Qt.LeftButton, Qt.MiddleButton):
            e.accept()          # dock 已处理左键语义；中键无语义
            return
        names = {Qt.RightButton: "右键点击", Qt.XButton1: "侧键 X1 点击",
                 Qt.XButton2: "侧键 X2 点击"}
        self._dbg(names.get(e.button(), f"鼠标按键 {e.button()}"))
        if not self.event_hook:
            return
        mapping = {
            Qt.RightButton: Event.RIGHT,
            Qt.XButton1: Event.X1,
            Qt.XButton2: Event.X2,
        }
        ev = mapping.get(e.button())
        if ev:
            self.event_hook(ev)

    def wheelEvent(self, e) -> None:  # noqa: N802
        """滚轮：delta 累积，每满 120×灵敏度 才动一格（D-028 修一次跳两格）。"""
        if self.global_mode:
            e.accept()          # T-014：事件由全局钩子投递，Qt 路径抑制
            return
        if not self.event_hook:
            return
        dy = e.angleDelta().y()
        self._wheel_acc += dy
        step = 120 * max(1, int(self.cfg.wheel_sens))
        fired = False
        while self._wheel_acc >= step:
            self._dbg(f"滚轮 delta={dy:+d}（累积 {self._wheel_acc}/{step} 达标）→ 滚轮上")
            self.event_hook(Event.SCROLL_UP)
            self._wheel_acc -= step
            fired = True
        while self._wheel_acc <= -step:
            self._dbg(f"滚轮 delta={dy:+d}（累积 {self._wheel_acc}/-{step} 达标）→ 滚轮下")
            self.event_hook(Event.SCROLL_DOWN)
            self._wheel_acc += step
            fired = True
        if not fired:
            self._dbg(f"滚轮 delta={dy:+d} → 累积 {self._wheel_acc:+d}/{step:+d} 未达阈值 → 不移动、不发键",
                      instant=True)

    def closeEvent(self, e) -> None:  # noqa: N802
        self._save_pos()
        if self._settings_dlg is not None:
            self._settings_dlg.close()
        super().closeEvent(e)
        QApplication.instance().quit()   # Tool 窗口不计 quitOnLastWindowClosed，显式退出

    # ---------- 渲染 ----------

    def render(self, snap, echo_text: str = "") -> None:
        self.dock.update_content(snap.items, snap.idx)
