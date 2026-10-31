"""T-049 回归：采样坐标全局化 + glass_paint 模块化拆分（D-048）

① capture_rect 纯函数：GDI 全局虚拟屏物理坐标（D-047 取证：旧 screen-local
   坐标在副屏采到别的屏幕——B 图墙纸 vs C 图聊天窗口）
② glass_paint 六个绘制函数直接冒烟（CapCtx → QPainter 命令，无窗口依赖）
③ 自排除契约：worker 在捕获前 affinity 置位、捕获后复位（代码级断言——
   真机排除率由 spikes/spike_self_exclude.py 实证 0.0%）
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, QRectF, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.backdrop import capture_rect  # noqa: E402
from ui.glass_paint import (CapCtx, paint_body, paint_depth, paint_edges,  # noqa: E402
                            paint_selected_glow, paint_shadow, paint_sheen,
                            paint_top_env_arcs)
from ui.theme import SKINS, TEXTURES  # noqa: E402


class TestCaptureRect(unittest.TestCase):
    def test_negative_secondary_screen_dpr1(self):
        """D-047 用户场景：副屏全局 (-1879, 805) → 必须原样输出全局物理坐标
        （旧实现输出 (681, 977) = 主屏位置 = 采到别的屏幕）。"""
        self.assertEqual(capture_rect(QRect(-1879, 805, 1385, 118), 1.0),
                         (-1879, 805, 1385, 118))

    def test_dpr_150(self):
        """逻辑 → 物理换算（1.5× 屏；Python round 为银行家舍入：1384.5→1384）。"""
        self.assertEqual(capture_rect(QRect(-1252, 536, 923, 78), 1.5),
                         (-1878, 804, 1384, 117))

    def test_primary_screen(self):
        self.assertEqual(capture_rect(QRect(100, 200, 300, 400), 1.0),
                         (100, 200, 300, 400))


class TestGlassPaint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _paint_all(self, skin_key, tex_key, selected, bd, light):
        img = QImage(360, 100, QImage.Format.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        try:    # try/finally：绘制异常时也必须 end()，否则泄漏活动
                # QPainter → QImage GC 时 qFatal（D-046 教训，测试同理）
            rect = QRectF(140, 20, 80, 60)
            ctx = CapCtx(rect=rect, r=10, cx0=180, u=36,
                         skin=SKINS[skin_key], tex=TEXTURES[tex_key],
                         glass=0.8, trans=SKINS[skin_key].trans,
                         selected=selected, light=light, bd=bd,
                         bd_dpr=1.0, bd_off=QPointF(0, 0) if bd else None,
                         body_shadow_rect=rect.adjusted(0.7, 0.7, -0.7, -0.7))
            paint_selected_glow(p, ctx)
            paint_shadow(p, ctx)
            paint_body(p, ctx)
            paint_sheen(p, ctx)
            paint_depth(p, ctx)
            paint_edges(p, ctx)
            paint_top_env_arcs(p, ctx)
        finally:
            p.end()
        self.assertFalse(img.isNull())

    def test_all_skins_textures_paths(self):
        pm = QPixmap(360, 100)
        pm.fill(QColor(30, 60, 90))
        for skin in SKINS:
            for tex in TEXTURES:
                self._paint_all(skin, tex, False, None, None)
                self._paint_all(skin, tex, True, None, None)
                if SKINS[skin].trans > 0:
                    self._paint_all(skin, tex, False, pm, None)
                    self._paint_all(skin, tex, False, pm, QPointF(180, 30))

    def test_worker_affinity_contract(self):
        """worker 源码必须包含 捕获前置位 → 捕获 → finally 复位 的结构。"""
        src = Path("ui/backdrop.py").read_text(encoding="utf-8")
        self.assertIn("SetWindowDisplayAffinity(hwnd, 0x11)", src)
        self.assertIn("finally:", src)
        self.assertIn("SetWindowDisplayAffinity(hwnd, 0)", src)
        # 置位先于捕获
        self.assertLess(src.find("SetWindowDisplayAffinity(hwnd, 0x11)"),
                        src.find("_gdi_capture_bgrx(x, y, w, h)",
                                 src.find("def _work")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
