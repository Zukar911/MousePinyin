"""Dock 环形连续鱼眼回归 —— D-036：环形距离场 + 回绕连续动画（无硬切）

需求链：①滚动时未选中块位置跳动（晕）→ ②鱼眼正弦不能删 → ③等比 2D →
④回绕时旧侧放大效果被硬切（D-028② 瞬移）→ 用户选定方案 A：**环形连续场**——
衰减距离取环上 min(|i-f|, n-|i-f|)，首尾互为环邻居（焦点在 0 时 23 号保持
1.65×）；回绕沿环连续动画（旧侧渐收/新侧渐起），D-028② 瞬移被取代。

验证：
1. _x0/_e_ref 动画全程不变；真实动画到位
2. 环距 >2.5 的键帽 scale 恒 1.0；焦点左侧（累加序）环远帽位置钉在基线
3. 远端帽位置沿环恒定（E·k = E_ref 恒等式，整数焦点零漂移）
4. 缝合对称：f=23.5 时首尾两帽放大相等（半鼓包各半）
5. 回绕连续：set_target(0)（当前 23）动画终点 = 24（非瞬移），步长 ≤ n/2
6. 等比 2D + 累加排布永不叠压 + 端点不裁切
7. 像素回归：中部滚动时两端区域像素逐字节一致
8. D-024 正弦场数学性质（环上距离）；选中判定随环移交
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QAbstractAnimation, QPointF, QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.dock_strip import MAXS, S_CAP, SPREAD, DockStrip, cap_units  # noqa: E402

ITEMS = ["b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j",
         "q", "x", "zh", "ch", "sh", "r", "z", "c", "s", "y", "w", ""]
N = len(ITEMS)


def make_dock(items=None):
    dock = DockStrip()
    dock.update_content(list(items if items is not None else ITEMS), 0)
    dock._anim.stop()
    return dock


def frame_layout(dock, f):
    """复算 paintEvent 的布局（cx/wd/sd），供数学断言（镜像 D-039 峰值保持）。"""
    n = len(dock._items)
    e_raw = dock._energy_units(f) * dock._u
    peak_extra = sum(
        (dock._scale_of(i, f) - 1.0) * cap_units(dock._items[i]) * dock._u
        for i in range(n) if dock._ring_dist(i, f) <= 0.5)
    nb_raw = e_raw - peak_extra
    nb_target = dock._e_ref - peak_extra
    if nb_raw > 1e-6 and nb_target > 0:
        k_nb = nb_target / nb_raw
    else:
        k_nb = 0.0 if nb_target <= 0 else 1.0
    cx, wd, sd = [0.0] * n, [0.0] * n, [0.0] * n
    x = dock._x0
    for i in range(n):
        raw = dock._scale_of(i, f)
        if dock._ring_dist(i, f) <= 0.5:
            s = raw
        else:
            s = min(1.0 + (raw - 1.0) * k_nb, S_CAP)
        sd[i] = s
        wd[i] = cap_units(dock._items[i]) * dock._u * s
        cx[i] = x + wd[i] / 2.0
        x += wd[i] + dock._gap
    return cx, wd, sd


def img_bytes(img):
    return (img.width(), img.height(), bytes(img.constBits()))


class TestRingFisheye(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    # ---------- 1. 锚点与能量基准恒定 ----------

    def test_anchor_immutable_during_animation(self):
        dock = make_dock()
        x0, e_ref = dock._x0, dock._e_ref
        for f in (0.3, 1.7, 11.2, 23.0, 23.7):
            dock.set_focus(f)
            dock.repaint()
        self.assertEqual(dock._x0, x0)
        self.assertEqual(dock._e_ref, e_ref)

    def test_real_animation_reaches_target(self):
        dock = make_dock()
        x0 = dock._x0
        dock.set_target(10)
        if dock._anim.state() == QAbstractAnimation.State.Running:
            dock._anim.setCurrentTime(160)
        dock._anim.stop()
        self.assertAlmostEqual(dock._focus, 10.0)
        self.assertEqual(dock._x0, x0)

    # ---------- 2. 环距 >2.5 的帽 scale 恒 1.0；累加序前段钉在基线 ----------

    def test_ring_far_caps_scale_one(self):
        dock = make_dock()
        # f=12：环距 >2.5 的帽 = 0..8 与 16..23
        _, _, sd = frame_layout(dock, 12.0)
        for i in list(range(0, 9)) + list(range(16, 24)):
            self.assertEqual(sd[i], 1.0, f"f=12 {i} 号帽应在鱼眼半径外")
        # f=23：缝合邻居 0/1 参与鱼眼，2..20 恒 1.0
        _, _, sd = frame_layout(dock, 23.0)
        for i in range(2, 21):
            self.assertEqual(sd[i], 1.0, f"f=23 {i} 号帽应在鱼眼半径外")

    def test_left_segment_pinned_at_baseline(self):
        """累加序在鼓包之前的环远帽：位置 == 基线（焦点在行中/右部时）。"""
        dock = make_dock()
        for f in (12.0, 18.0):
            cx, _, _ = frame_layout(dock, f)
            for i in range(0, 9):
                self.assertAlmostEqual(cx[i], dock._cx[i], places=6,
                                       msg=f"f={f} {i} 号帽偏离基线")

    # ---------- 3. 远端帽沿环恒定（E·k = E_ref 恒等式） ----------

    def test_far_cap_constant_along_ring(self):
        dock = make_dock()
        # 鼓包完全位于 17 号之前的焦点集：prefix 能量 = E·k = E_ref 恒等
        ref = None
        for f in (2.0, 6.0, 10.0, 12.0, 14.0):
            cx, _, _ = frame_layout(dock, f)
            if ref is None:
                ref = cx[17]
            self.assertAlmostEqual(cx[17], ref, places=6, msg=f"f={f}")
        # 缝合跨越（f=0/23，鼓包一半在行首一半在行尾）时，中段帽有
        # 一次性的平滑滑移（缝侧能量换边），幅度有界 ≤ 1.0U：
        cx_seam, _, _ = frame_layout(dock, 0.0)
        self.assertLessEqual(abs(cx_seam[17] - ref), dock._u)

    # ---------- 4. 缝合对称（回绕中点两半鼓包相等） ----------

    def test_seam_symmetry(self):
        dock = make_dock()
        cx, wd, sd = frame_layout(dock, 23.5)
        # 归一化 k 对两半鼓包同增益 → 首尾严格对称；数值 = 原始曲线 × k
        self.assertAlmostEqual(sd[0], sd[23], places=6)
        self.assertAlmostEqual(sd[1], sd[22], places=6)
        self.assertGreaterEqual(sd[0], 1.0 + (MAXS - 1.0) * 0.8)  # ≥ 原始峰值
        self.assertLessEqual(sd[0], S_CAP)

    # ---------- 5. 回绕连续动画（取代 D-028② 瞬移） ----------

    def test_ring_field_invariant_under_focus_drift(self):
        """D-037 回归：多次回绕后 focus 无界增长（如 171 = 7 圈 + 3），
        放大场/布局必须与同余基准帧完全一致。真机 bug：min(|i-f|, n-|i-f|)
        未先取模，focus 漂出 [0,n] 后 n-d 为负、正弦参数随序号振荡 → 整行
        尺寸错乱（用户截屏的"排列全乱"）。"""
        dock = make_dock()
        cases = ((3.0, (3.0 + N * 7, 3.0 - N * 5)),      # ≡3
                 (0.0, (float(N * 12),)),                # ≡0
                 (11.5, (float(N * 31 + 11.5),)))        # ≡11.5 半格步进
        for base, drifts in cases:
            cxb, wdb, sdb = frame_layout(dock, base)
            for f in drifts:
                cx, wd, sd = frame_layout(dock, f)
                self.assertEqual(sd, sdb, f"f={f} 缩放场漂移")
                self.assertEqual(cx, cxb, f"f={f} 布局漂移")
                self.assertEqual(wd, wdb, f"f={f} 宽度漂移")

    def test_wrap_animates_through_seam(self):
        dock = make_dock()
        dock._anim.stop()
        dock._focus = 23.0
        dock._target = 23
        dock.set_target(0)
        self.assertEqual(dock._target, 0)
        self.assertEqual(dock._anim.state(), QAbstractAnimation.State.Running,
                         "回绕应连续动画而非瞬移")
        end = dock._anim.endValue()
        self.assertEqual(end, 24.0)                     # 环上最近等价点
        self.assertLessEqual(abs(end - dock._focus), N / 2)  # 永取最短环向
        dock._anim.setCurrentTime(160)
        dock._anim.stop()
        self.assertAlmostEqual(dock._focus, 24.0)
        # 反向：24 → 23 应动画回 23（不跨整行）
        dock.set_target(23)
        self.assertEqual(dock._anim.endValue(), 23.0)

    # ---------- 6. 等比 2D + 永不叠压 + 不裁切 ----------

    def test_proportional_2d_scaling(self):
        dock = make_dock()
        u = dock._u
        cx, wd, sd = frame_layout(dock, 3.0)
        for i in range(N):
            base = cap_units(ITEMS[i]) * u
            self.assertAlmostEqual(wd[i], base * sd[i], places=6)
        # D-039：焦点峰值不参与归一化——落定精确 MAXS（任何位置）
        self.assertAlmostEqual(sd[3], MAXS, places=6)
        self.assertAlmostEqual(sd[0], 1.0, places=6)     # 环距 3 → 1.0
        self.assertGreater(sd[4], 1.0)

    # ---------- D-039 峰值保持：放大永不缩小 ----------

    def test_landing_peak_exact_everywhere(self):
        """任何位置落定 = 精确 MAXS（含 zh/ch/sh 宽帽区——用户 bug：
        旧归一化连峰值一起缩放，宽帽区落定仅 1.68×）。"""
        dock = make_dock()
        for i in range(N):
            _, _, sd = frame_layout(dock, float(i))
            self.assertAlmostEqual(sd[i], MAXS, places=9,
                                   msg=f"{i} 号帽（{ITEMS[i]!r}）落定峰值漂移")

    def test_transit_peak_constant_and_below_landing(self):
        """过渡峰值恒定（与位置无关）且 < 落定值 → 放大全单调增长、永不缩小。"""
        dock = make_dock()
        import math
        expect = 1.0 + (MAXS - 1.0) * math.sin(math.pi / 2 * 0.8)
        for i in range(N):
            nxt = (i + 1) % N
            _, _, sd = frame_layout(dock, i + 0.5)
            self.assertAlmostEqual(sd[nxt], expect, places=9,
                                   msg=f"{i}→{nxt} 过渡峰值漂移")
            self.assertLess(sd[nxt], MAXS, f"{i}→{nxt} 过渡峰值 ≥ 落定（会缩小）")

    def test_no_overlap_any_focus(self):
        dock = make_dock()
        gap = dock._gap
        for f in (0.0, 3.7, 11.5, 22.0, 23.0, 23.5):
            cx, wd, _ = frame_layout(dock, f)
            for a in range(N - 1):
                clearance = (cx[a + 1] - wd[a + 1] / 2) - (cx[a] + wd[a] / 2)
                self.assertGreaterEqual(clearance, gap - 0.01,
                                        f"f={f} {a}|{a+1} 叠压")

    def test_no_clip_any_focus(self):
        dock = make_dock()
        limit_r = dock.width() - dock._pad_r
        for f in (0.0, 1.0, 11.5, 22.4, 23.0, 23.5):
            cx, wd, _ = frame_layout(dock, f)
            self.assertGreaterEqual(cx[0] - wd[0] / 2, dock._x0 - 0.01)
            self.assertLessEqual(cx[N - 1] + wd[N - 1] / 2, limit_r + 0.01,
                                 f"f={f} 右端侵入 ⚙/✕ 保留区")
        u = dock._u
        self.assertGreaterEqual(dock.height(), u * (S_CAP + 0.10))

    # ---------- 7. 像素回归：中部滚动时两端区域逐字节一致 ----------

    def test_pixels_stable_both_far_sides(self):
        dock = make_dock()
        dock.resize(dock.sizeHint())
        u = dock._u
        imgs = {}
        for f in (10.0, 10.5, 11.0):
            dock._focus = f
            dock.repaint()
            imgs[f] = dock.grab().toImage()
        left_x1 = int(dock._cx[5])
        right_x0 = int(dock._cx[16] - cap_units(ITEMS[16]) * u / 2 - 2)
        w = imgs[10.0].width() - right_x0
        for tag, box in (("左", QRect(0, 0, left_x1, imgs[10.0].height())),
                         ("右", QRect(right_x0, 0, w, imgs[10.0].height()))):
            ref = img_bytes(imgs[10.0].copy(box))
            for f, img in imgs.items():
                self.assertEqual(img_bytes(img.copy(box)), ref,
                                 f"f={f} {tag}端远区像素变化 → 键帽动了")

    # ---------- 8. 正弦场（环上距离）+ 选中移交 ----------

    def test_ring_sine_field(self):
        import math
        dock = make_dock()
        s = dock._scale_of
        self.assertAlmostEqual(s(3, 3.0), MAXS)
        self.assertAlmostEqual(s(6, 3.0), 1.0)
        self.assertAlmostEqual(s(0, 3.0), 1.0)
        # D-036 环形语义：缝合邻居按环距走同一条 D-024 曲线
        self.assertAlmostEqual(s(23, 0.0),
                               1.0 + (MAXS - 1.0) * math.sin(math.pi / 2 * 0.6),
                               places=6)
        self.assertAlmostEqual(s(22, 0.0),
                               1.0 + (MAXS - 1.0) * math.sin(math.pi / 2 * 0.2),
                               places=6)
        prev = MAXS
        for k in range(1, 26):                          # 半径内单调衰减
            v = s(3 + k / 10.0, 3.0)
            self.assertLessEqual(v, prev + 1e-9)
            prev = v

    def test_selected_follows_ring(self):
        dock = make_dock()
        for f, i in ((3.0, 3), (3.49, 3), (3.51, 4), (4.0, 4),
                     (23.7, 0), (23.3, 23)):
            sel = [j for j in range(N)
                   if dock._ring_dist(j, f) < 0.5]
            self.assertEqual(sel, [i], f"f={f}")


    # ---------- D-040 缩放单调：调大永不变小 ----------

    def test_scale_monotonic_wide_screen_full_size(self):
        """用户场景（宽 2560 副屏）：scale 0.7→1.5 扫描，u/窗宽单调不减；
        1.3× 键帽完全不压缩（u = u_base）——旧实现被 primaryScreen（1707
        窄屏）压缩 + 开销随 u_base 自噬 → u(1.3) < u(1.2)（调大变小）。"""
        from PySide6.QtCore import QRect
        dock = make_dock()
        dock._avail_geometry = lambda: QRect(-2560, -172, 2560, 1440)
        prev_u, prev_w = 0.0, 0
        for sc100 in range(70, 151, 5):
            dock._cfg.scale = sc100 / 100
            dock.set_config(dock._cfg)
            self.assertGreaterEqual(dock._u, prev_u - 1e-9,
                                    f"scale={sc100/100} u 变小")
            self.assertGreaterEqual(dock.width(), prev_w - 1,
                                    f"scale={sc100/100} 窗宽变小")
            prev_u, prev_w = dock._u, dock.width()
        dock._cfg.scale = 1.3
        dock.set_config(dock._cfg)
        self.assertAlmostEqual(dock._u, 40.0 * 1.3, places=6,
                               msg="宽副屏 1.3× 应完全不压缩")

    def test_scale_monotonic_narrow_screen(self):
        """窄主屏（1707）：放不下时 u 走压缩上限——上限与 scale 无关的
        常数（定点解），u 单调不减、绝不回缩。"""
        from PySide6.QtCore import QRect
        dock = make_dock()
        dock._avail_geometry = lambda: QRect(0, 0, 1707, 1067)
        prev_u = 0.0
        for sc100 in range(70, 151, 5):
            dock._cfg.scale = sc100 / 100
            dock.set_config(dock._cfg)
            self.assertGreaterEqual(dock._u, prev_u - 1e-9,
                                    f"scale={sc100/100} u 变小（窄屏）")
            prev_u = dock._u


    # ---------- D-042 背景折射渲染冒烟 ----------

    def test_backdrop_refraction_render_smoke(self):
        """透明皮肤 + 背景采样图：键帽走透镜折射绘制路径，不抛异常。"""
        from PySide6.QtGui import QColor, QPixmap
        dock = make_dock()
        pm = QPixmap(640, 120)
        pm.fill(QColor(30, 60, 90))
        dock._backdrop = pm
        dock._backdrop_dpr = 1.0
        dock._backdrop_off = QPointF(0, 0)
        dock._cfg.skin = "air"               # trans=0.45 → 背景折射路径
        dock._relayout()
        for f in (0.0, 11.5, 23.5):
            dock._focus = f
            dock.repaint()                   # 不应抛异常
        dock._light = QPointF(60, 30)
        dock.repaint()
        # 无背景（None）回落原路径也不异常
        dock._backdrop = None
        dock.repaint()

    def test_backdrop_refraction_render_smoke_transparent_all(self):
        """三款透明皮肤 × 背景图全渲染冒烟。"""
        from PySide6.QtGui import QColor, QPixmap
        dock = make_dock()
        pm = QPixmap(640, 120)
        pm.fill(QColor(90, 30, 60))
        dock._backdrop = pm
        dock._backdrop_dpr = 1.0
        dock._backdrop_off = QPointF(4, 20)
        for skin in ("air", "ice", "rose"):
            dock._cfg.skin = skin
            dock._relayout()
            dock.set_focus(7.0)
            dock.repaint()


if __name__ == "__main__":
    unittest.main(verbosity=2)
