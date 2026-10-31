"""ui/dock_strip.py —— 左锚定等比鱼眼键帽栏（macOS Dock 取意，D-024/D-028/D-034/D-035）

- **完整等比鱼眼**（D-024 正弦场原样：焦点 1.8×、邻居正弦衰减、影响 2.5 格；
  宽×高同比例放大，非纵向拉伸）+ **邻居自然让位**（累加排布，键帽边缘间距
  恒等于 gap，永不叠压）
- **左端锚定（D-035 根治"整行跳动"）**：行左缘 _x0 永久钉死（只在列表/配置
  变化时重算），逐帽累加排布——焦点右侧时左侧未选中块位置零变化；位移只
  发生在鱼眼鼓包经过的局部（D-028"每帧整行重新居中"已删除，那是焦点一动
  整行平移的根源）
- **占位恒定归一化（D-035）**：每帧按 k = E_ref/E(f) 缩放放大场（E = 鼓包
  总宽），行总足迹恒定 → 右侧远端块钉在基线+常量，不随鼓包呼吸摆动
- **环形连续场（D-036）**：衰减距离取环上 min(|i-f|, n-|i-f|)——首尾互为
  环邻居（焦点在 0 时 23 号保持 1.65×）；回绕沿环连续动画（旧侧渐收/
  新侧渐起，无硬切；D-028②"跨半圈瞬移"被取代，"整行横穿"依然不会发生）
- 滚轮移动"选择框"（浮点焦点，160ms OutCubic）
- **点击语义（F-001 合规，D-028/D-032/D-033）**：左键 = 确认当前选中项
  （confirm_requested，与鼠标坐标无关）；点未选中键 = 完全忽略；hover 已移除
- 玻璃质感七层（零 blur）：投影/渐变底/斜光带/内反光/三段边光/焦点辉光
- 显示：零声母空串 → 〇；v → ü
"""

import math

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation,
                            QPointF, QRectF, Qt, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

from ui.glass_paint import (CapCtx, paint_body, paint_depth,
                            paint_edges, paint_selected_glow,
                            paint_shadow, paint_sheen,
                            paint_top_env_arcs)
from ui.theme import Config

MAXS = 1.8      # 焦点项最大放大倍数（D-024 鱼眼，中部位置）
SPREAD = 2.5    # 鱼眼正弦影响半径（格，D-024 原参数）
S_CAP = 2.05    # 归一化后单帽放大上限（端部能量补偿钳制，配 2.25U 高度）


def cap_units(text: str) -> float:
    """键帽宽度（U）：1 字母 1U，每多 1 字母 +0.25U，特殊项固定宽，上限 3.5U。"""
    if text.startswith("␣") or text.startswith("↕"):
        return 3.0
    if len(text) <= 1:
        return 1.0
    return min(1.0 + 0.25 * (len(text) - 1), 3.5)


NO_PEN = QPen(Qt.NoPen)


def _disp(item: str) -> str:
    """显示转换：零声母空串 → 〇；内部 v → ü。"""
    if not item.strip():
        return "〇"
    if item.startswith("␣"):
        return item
    return item.replace("v", "ü")


class DockStrip(QWidget):
    confirm_requested = Signal(int)   # 确认当前项（点选中键 / 空白左键）→ 真实 idx
    size_changed = Signal()           # 项目数/尺寸变化 → 窗口重算

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[str] = []
        self._focus: float = 0.0          # 浮点焦点（动画属性）
        self._target: int = 0
        self._cx: list[float] = []        # 基线中心（1.0 尺寸，重排时计算）
        self._x0 = 20.0                   # 行左缘锚点（D-035：永久钉死）
        self._e_ref = 0.0                 # 鼓包基准能量（占位恒定归一化，D-035）
        # 属性名禁用 "focus"（与 QWidget 内建属性冲突 → 动画静默失效，D-026 教训）
        self._anim = QPropertyAnimation(self, b"focusPos")
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._cfg: Config = Config()
        self._u_base = 40.0
        self._u = self._u_base
        self._gap = 6.0
        self._pad_r = 94.0
        self._tx = 20
        self._light = None              # D-038 光标光源（本窗局部坐标；窗口轮询注入）
        self._backdrop = None           # D-042 背景折射源（窗口采样器注入）
        self._units_capacity = 0.0      # D-050 容量包络：历史最宽层的键帽总量 U
        self._n_capacity = 0            # D-050 容量包络：历史最多项数
        self._backdrop_dpr = 1.0
        self._backdrop_off = None
        # D-032：无 mouseTracking（hover 反馈已移除，选中只由滚轮决定）

    # ---------- 配置与尺寸 ----------

    def set_config(self, cfg: Config) -> None:
        self._cfg = cfg
        self._apply_metrics()
        self._relayout()
        self.update()

    def _apply_metrics(self) -> None:
        sc = self._cfg.scale
        self._u_base = 40.0 * sc                 # 1U 基准（键帽几何只随 scale）
        self._gap = max(4.0, self._u_base * 0.15)
        self._pad_r = max(94.0, self._u_base * 2.4)   # ⚙/✕ 预留（⠿ 在外框顶中央）
        self._tx = int(min(self._cfg.font_size * sc, self._u_base * 0.72))

    def text_px(self) -> int:
        return self._tx

    def _avail_geometry(self):
        """D-040 布局目标屏 = 窗口所在屏（可为负坐标副屏），退避主屏。
        旧实现固定 primaryScreen：窗口在宽副屏时被窄主屏无谓压缩
        （用户"1.3× 后外框/键帽变小"根因①）。"""
        win = self.window()
        if win is not None:
            ax, ay = win.x() + win.width() // 2, win.y()
            for s in QApplication.screens():
                if s.geometry().contains(ax, ay):
                    return s.availableGeometry()
        return QApplication.primaryScreen().availableGeometry()

    def _relayout(self) -> None:
        """D-050 **固定外框**：窗口宽度按**容量包络**（历史最宽层的键帽总量）
        计算一次，层级切换**零缩放零跳变**——窄层在固定框内左锚定排布、
        右侧留白，⚙/✕ 按钮位置恒定。
        u 的两级逻辑：容量层决定 u 上限（定点解，开销随最终 u 取值，D-040
        定点法沿用）；当前层在固定框内按自身项数自适应（放得下就用 u_base）。
        容量单调不减：只有出现更宽的新层才会扩一次框（正常流中声母层即最宽，
        启动时定型后不再变）。"""
        n = len(self._items)
        if n == 0:
            self._cx = []
            self._e_ref = 0.0
            self.setFixedHeight(int(self._u_base * 1.95))
            self.size_changed.emit()
            return
        total_units = sum(cap_units(x) for x in self._items)
        if total_units > self._units_capacity:
            self._units_capacity = total_units
        if n > self._n_capacity:
            self._n_capacity = n
        avail_w = self._avail_geometry().width()
        u = self._u_base
        for _ in range(60):                    # 定点迭代（开销随最终 u 取值）
            gap = max(4.0, u * 0.15)
            pad = max(94.0, u * 2.4)
            grow = 3.0 * u + 8.0               # 鼓包包络常量（与 setFixedWidth 一致）
            max_w = max(360.0, avail_w * 0.92 - pad - 24.0)
            nu = max(18.0, min(self._u_base,
                               (max_w - gap * (self._n_capacity - 1) - grow)
                               / self._units_capacity))
            if abs(nu - u) < 1e-9:
                u = nu
                break
            u = nu
        self._u = u
        self._gap = max(4.0, u * 0.15)
        self._pad_r = max(94.0, u * 2.4)
        grow = 3.0 * u + 8.0            # 鼓包能量包络（≈2.65U 上界）+ 端部余量
        gap_total = self._gap * (self._n_capacity - 1)
        self.setFixedWidth(int(self._units_capacity * u + gap_total + grow
                               + self._pad_r + 24.0))
        self.setFixedHeight(int(u * 2.25))    # 2.05× 端部钳制 + 辉光余量
        self._tx = int(min(self._cfg.font_size * self._cfg.scale, u * 0.72))
        self._layout_base()
        self.size_changed.emit()

    def _layout_base(self) -> None:
        """D-050 基线与锚点：x0 由**容量包络**决定（配置不变则恒定）——层级
        切换时键帽左缘不动；_e_ref = 当前层鼓包基准能量（真实 u）。"""
        n = len(self._items)
        self._cx = []
        if n == 0:
            self._e_ref = 0.0
            return
        self._e_ref = self._energy_units(n // 2) * self._u
        base_w = [cap_units(x) * self._u for x in self._items]
        # D-050：x0 由**容量包络**决定（配置不变则恒定）——层级切换时键帽
        # 左缘不动、右侧留白给 ⚙/✕；窄层的鱼眼鼓包向右伸入留白区
        row_w_cap = (self._units_capacity * self._u
                     + (self._n_capacity - 1) * self._gap)
        grow_cap = 3.0 * self._u + 8.0
        avail = self.width() - self._pad_r
        self._x0 = max(8.0, (avail - row_w_cap - grow_cap) / 2.0)
        x = self._x0
        for bw in base_w:
            self._cx.append(x + bw / 2.0)
            x += bw + self._gap

    # ---------- 动画属性 ----------

    def get_focus(self) -> float:
        return self._focus

    def set_focus(self, v: float) -> None:
        self._focus = v
        self.update()

    focusPos = Property(float, get_focus, set_focus)

    # ---------- 数据接口 ----------

    def update_content(self, items: list[str], idx: int) -> None:
        """渲染入口：列表变化 → 重排+焦点归零；否则动画滚到新 idx。"""
        if items != self._items:
            self._items = list(items)
            self._anim.stop()
            self._focus = 0.0
            self._target = idx % len(self._items) if self._items else 0
            self._relayout()
            self.update()
        else:
            self.set_target(idx)

    def set_target(self, idx: int) -> None:
        """状态机 idx 变化：焦点沿环上最短方向**连续动画**（D-036）。
        回绕（如 23→0）动画终点取当前浮点焦点的最近环上等价表示（24），
        旧侧鼓包渐收、新侧渐起，全程无硬切——D-028②"跨半圈瞬移"被取代
        （其反对的"整行横穿"依然不会发生：位移只在首尾两端局部过渡）。"""
        if not self._items:
            return
        n = len(self._items)
        idx %= n
        if idx == self._target:
            return
        end = idx + n * round((self._focus - idx) / n)   # 最近环上等价点
        self._target = idx
        self._anim.stop()
        self._anim.setStartValue(self._focus)
        self._anim.setEndValue(float(end))
        self._anim.start()

    # ---------- 鱼眼场（D-024 正弦曲线 + D-035 占位恒定 + D-036 环形连续） ----------

    def _ring_dist(self, i: int, f: float) -> float:
        """环上最短距离：**先按 n 取模到 [0, n)**，再取 min(d, n-d)。
        焦点是无界浮点（D-036 回绕连续动画逐格累加，如 24、25…100+），
        必须先取模——否则 |i-f|>n 时 n-d 为负、正弦参数越过 π/2 随序号
        振荡，整行放大场错乱（真机多次滚轮复现的"排列全乱"根因，D-037）。"""
        n = len(self._items)
        if n == 0:
            return 0.0
        d = abs(i - f) % n
        return min(d, n - d)

    def _scale_of(self, i: int, f: float) -> float:
        """D-024 原鱼眼曲线（环上距离，D-036）：焦点 1.8×，邻居正弦衰减，
        影响 2.5 格（纯函数语义，n 由 _items 提供）。"""
        d = self._ring_dist(i, f)
        t = max(0.0, 1.0 - d / SPREAD)
        return 1.0 + (MAXS - 1.0) * math.sin(math.pi / 2.0 * t)

    def _energy_units(self, f: float) -> float:
        """鼓包能量（U 计）：Σ (scale-1)·键帽宽 U —— 与 _u 无关的线性系数。
        环形场下整数焦点能量恒定（首尾互补），半格步进略有凹谷由 k 归一化。"""
        return sum((self._scale_of(i, f) - 1.0) * cap_units(x)
                   for i, x in enumerate(self._items))

    # ---------- 鼠标 ----------

    def wheelEvent(self, e) -> None:  # noqa: N802
        """滚轮上浮：Qt6 不保证向父级传播（D-025），显式转发。"""
        e.ignore()
        p = self.parentWidget()
        if p is not None:
            QApplication.sendEvent(p, e)

    def confirm_target(self) -> int | None:
        """左键确认对象 = 滚轮导航的逻辑索引 `_target`（D-033）。
        **与鼠标坐标无关**：不用命中索引、不用悬浮、不用动画插值（_focus）。
        无候选时返回 None（不确认）。"""
        n = len(self._items)
        if n == 0:
            return None
        return int(self._target) % n

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if getattr(self.window(), "global_mode", False):
            e.accept()          # T-014：事件由全局钩子投递，Qt 路径抑制
            return
        if e.button() == Qt.LeftButton:
            # D-033 宪法语义：左键 = 统一"确认当前选中项"，与鼠标位置无关——
            # 鼠标停在选中项/未选中项/空白处，确认的都是滚轮选中的那一项。
            # 一次按下仅此一次确认（release 不处理；无全局监听路径）。
            idx = self.confirm_target()
            dbg = getattr(self, "on_debug", None)
            if idx is not None:
                if dbg:
                    dbg(f"左键 → 确认当前选中项 [{idx}] '{self._items[idx]}'（与鼠标位置无关）")
                self.confirm_requested.emit(idx)
            else:
                if dbg:
                    dbg("左键按下（无候选）→ 忽略")
            e.accept()
            return
        e.ignore()              # 中/右/侧键传父（切选字/退格）

    # D-032：hover 视觉反馈整体移除——鼠标移入/移出任何键帽均不改变
    # 颜色/透明度/大小/描边/光效/光标，选中状态只由滚轮导航决定
    # （原 mouseMoveEvent/leaveEvent/_hover 已删除）
    # D-033：左键不再使用鼠标命中（_hit/_cap_rects 已删）——确认对象只看
    # 滚轮逻辑索引；⚙/✕/⠿ 为独立控件不受影响。

    # ---------- 绘制 ----------

    def paintEvent(self, e) -> None:  # noqa: N802
        n = len(self._items)
        if n == 0:
            return
        if len(self._cx) != n:             # 防御：_items 被外部直改时兜底重排
            self._layout_base()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        skin = self._cfg.skin_obj
        glass = self._cfg.glass
        f = self._focus

        # D-039 峰值保持归一化：焦点帽（环距 ≤0.5，静止 1 个/过渡 2 个）
        # **不参与 k 缩放**——任何位置落定都精确 MAXS、过渡峰值恒定
        # （与位置无关）→ 放大单调增长、永不缩小。旧方案 k=E_ref/E(f) 连
        # 峰值一起缩放，E(f) 随局部帽宽（zh/ch/sh 1.25U）变化 → 宽帽区落定
        # 仅 1.68× 且落定 < 过渡峰值（用户"放大到最后还是会出现缩小"根因）。
        # 邻居按剩余预算归一（k_nb），行总足迹仍恒 = E_ref → 远端块钉死不变。
        e_raw = self._energy_units(f) * self._u
        peak_extra = sum(
            (self._scale_of(i, f) - 1.0) * cap_units(self._items[i]) * self._u
            for i in range(n) if self._ring_dist(i, f) <= 0.5)
        nb_raw = e_raw - peak_extra
        nb_target = self._e_ref - peak_extra
        if nb_raw > 1e-6 and nb_target > 0:
            k_nb = nb_target / nb_raw
        else:
            k_nb = 0.0 if nb_target <= 0 else 1.0

        # 等比 2D 鱼眼布局：从 _x0 逐帽累加（边缘间距恒 = gap，永不叠压）
        cx = [0.0] * n
        wd = [0.0] * n
        sd = [0.0] * n
        x = self._x0
        for i in range(n):
            raw = self._scale_of(i, f)
            if self._ring_dist(i, f) <= 0.5:
                s = raw                                   # 峰值不缩放（D-039）
            else:
                s = min(1.0 + (raw - 1.0) * k_nb, S_CAP)
            sd[i] = s
            wd[i] = cap_units(self._items[i]) * self._u * s
            cx[i] = x + wd[i] / 2.0
            x += wd[i] + self._gap

        bottom = self.height() - self._u * 0.10

        # 按环上距离排序绘制——放大帽永远在最上层；必须用环距而非原始
        # |i-f|：无界焦点下等距邻居的 raw 值不同会导致绘制顺序翻转、
        # 抗锯齿叠层随焦点漂移变化（D-037）
        order = sorted(range(n), key=lambda i: -self._ring_dist(i, f))
        for i in order:
            try:   # D-048 制度化防御：绘制异常不得泄漏活动 QPainter → qFatal
                self._draw_cap(p, cx[i], bottom, wd[i], sd[i], skin, glass, f, i)
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
        p.end()

    def _draw_cap(self, p: QPainter, cx0: float, bottom: float, w: float,
                  s: float, skin, glass: float, f: float, i: int) -> None:
        """键帽绘制（D-048 起为薄委托）：玻璃/光效全部在 ui/glass_paint.py
        （模块化债清偿，02 §10.4④）——本方法只构造 CapCtx + 画文字，
        保持方法名以兼容既有源码级测试断言（test_hover_removed）。"""
        item = self._items[i]
        h = self._u * s                    # 等比：高 = U×s（D-035：宽同比例）
        selected = self._ring_dist(i, f) < 0.5   # D-032/D-036：选中只由焦点决定
        tex = self._cfg.texture_obj
        trans = getattr(skin, "trans", 0.0)

        x, y = cx0 - w / 2, bottom - h
        rect = QRectF(x, y, w, h)
        r = min(w, h) * 0.22
        ctx = CapCtx(rect=rect, r=r, cx0=cx0, u=self._u, skin=skin, tex=tex,
                     glass=glass, trans=trans, selected=selected,
                     light=self._light, bd=self._backdrop,
                     bd_dpr=getattr(self, "_backdrop_dpr", 1.0),
                     bd_off=getattr(self, "_backdrop_off", None),
                     body_shadow_rect=rect.adjusted(0.7, 0.7, -0.7, -0.7))
        paint_selected_glow(p, ctx)
        paint_shadow(p, ctx)
        paint_body(p, ctx)
        paint_sheen(p, ctx)
        paint_depth(p, ctx)
        paint_edges(p, ctx)
        paint_top_env_arcs(p, ctx)

        fs = max(9, int(self._tx * s))
        fnt = QFont("Microsoft YaHei")
        fnt.setPixelSize(fs)
        fnt.setBold(selected)
        p.setFont(fnt)
        tc = QColor(skin.accent_text) if selected else QColor(skin.text)
        p.setPen(QPen(tc))
        p.drawText(rect, Qt.AlignCenter | Qt.TextSingleLine, _disp(item))
