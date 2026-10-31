"""多显示器回归测试 —— D-029：负坐标屏锚定

模拟左侧显示器（原点负数）布局，验证：
1. _screen_containing 正确识别负坐标屏 / 主屏 / 屏外
2. _anchor_clamp 在负坐标可用区内保持锚点（坐标可为负）
3. 仅完全出界才拉回；吸底部分出界贴底
4. 层切换（宽声母层→窄韵母层）锚点不变的纯逻辑推演
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from ui.candidate_window import CandidateWindow  # noqa: E402

CW = CandidateWindow

# 模拟用户真实桌面布局：左侧屏负原点 + 主屏
LEFT = QRect(-2560, -172, 2560, 1440)
LEFT_AVAIL = QRect(-2560, -172, 2560, 1392)
PRIMARY = QRect(0, 0, 1707, 1067)
PRIMARY_AVAIL = QRect(0, 0, 1707, 1019)
GEOMS = [LEFT, PRIMARY]


class TestScreenContaining(unittest.TestCase):
    def test_negative_screen_found(self):
        self.assertEqual(CW._screen_containing(QPoint(-1400, 300), GEOMS), 0)

    def test_primary_screen_found(self):
        self.assertEqual(CW._screen_containing(QPoint(500, 300), GEOMS), 1)

    def test_offscreen_not_found(self):
        self.assertEqual(CW._screen_containing(QPoint(5000, 300), GEOMS), -1)


class TestAnchorClampNegative(unittest.TestCase):
    def test_anchor_kept_negative_coords(self):
        """负屏内锚点保持，坐标可为负（旧 max(0,·) 会截成 0 → 跳主屏）。"""
        nx, ny = CW._anchor_clamp(-1400, 50, 600, 78, LEFT_AVAIL)
        self.assertEqual((nx, ny), (-1400, 50))

    def test_layer_switch_keeps_anchor(self):
        """宽声母层(1300) → 窄韵母层(500)：顶边中心锚点不变、坐标仍负。"""
        anchor = -1400                       # 顶边中心 x
        nx_wide, ny_wide = CW._anchor_clamp(anchor - 650, 50, 1300, 78, LEFT_AVAIL)
        self.assertEqual((nx_wide, ny_wide), (-1400 - 650, 50))
        nx_narrow, ny_narrow = CW._anchor_clamp(anchor - 250, 50, 500, 78, LEFT_AVAIL)
        center_wide = nx_wide + 1300 // 2
        center_narrow = nx_narrow + 500 // 2
        self.assertEqual(center_wide, anchor)
        self.assertEqual(center_narrow, anchor)   # 锚点不动
        self.assertTrue(nx_narrow < 0)            # 坐标保持负

    def test_completely_off_pulled_back(self):
        """窗口完全离开目标屏 → 拉回屏内。"""
        nx, ny = CW._anchor_clamp(-2560 - 600, 50, 600, 78, LEFT_AVAIL)
        self.assertEqual(nx, LEFT_AVAIL.left())   # -2560
        nx2, _ = CW._anchor_clamp(100, 50, 600, 78, PRIMARY_AVAIL)
        self.assertEqual(nx2, 100)                # 屏内不动

    def test_bottom_snap(self):
        """吸底部分出界：底边贴可用区下缘（y 可为负屏的 top）。"""
        avail = QRect(-2560, -172, 2560, 1392)    # bottom = 1219
        _, ny = CW._anchor_clamp(-1400, 1180, 600, 78, avail)
        self.assertEqual(ny, 1220 - 78)           # bottom+1-h

    def test_primary_layout_still_snaps_bottom(self):
        """主屏吸底场景回归：底边超出 → 贴底。"""
        _, ny = CW._anchor_clamp(500, 990, 600, 78, PRIMARY_AVAIL)
        self.assertEqual(ny, PRIMARY_AVAIL.bottom() + 1 - 78)


if __name__ == "__main__":
    unittest.main(verbosity=2)
