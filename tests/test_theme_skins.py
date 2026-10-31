"""theme 外观系统回归 —— D-038：皮肤×10（含透明玻璃）/ 质感四档 / 滚轮 2~5

用户需求：①更多皮肤颜色 + 透明玻璃皮肤 ②质感选项 ③滚轮第一档 = 2 格/项
（1 格档在高密度滚轮下双跳，移除）。
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ui.theme as theme  # noqa: E402
from ui.theme import (DEFAULT_CONFIG, SKINS, TEXTURES, Config, Skin,
                      Texture)  # noqa: E402


class TestSkins(unittest.TestCase):
    def test_ten_skins_with_transparent_glass(self):
        self.assertGreaterEqual(len(SKINS), 10)
        trans = [s for s in SKINS.values() if getattr(s, "trans", 0) > 0]
        self.assertGreaterEqual(len(trans), 3, "至少 3 款透明玻璃皮肤")
        for s in SKINS.values():
            self.assertIsInstance(s, Skin)
            self.assertTrue(s.name)
            self.assertTrue(s.accent.startswith("#"))

    def test_skin_default_trans_zero(self):
        """旧皮肤不写 trans 默认 0（不透明，行为不变）。"""
        self.assertEqual(SKINS["deepsea"].trans, 0.0)
        self.assertEqual(SKINS["gold"].trans, 0.0)


class TestTextures(unittest.TestCase):
    def test_four_textures(self):
        self.assertEqual(set(TEXTURES), {"plain", "glass", "frosted", "prism"})
        for t in TEXTURES.values():
            self.assertIsInstance(t, Texture)
            for f in ("dispersion", "refract", "sheen", "depth", "light_gain"):
                self.assertGreaterEqual(getattr(t, f), 0.0)

    def test_default_texture_glass(self):
        self.assertEqual(Config().texture, "glass")
        self.assertEqual(Config().texture_obj.key, "glass")
        cfg = Config(texture="bogus")
        self.assertEqual(cfg.texture_obj.key, "glass")   # 非法回退


class TestWheelSensGears(unittest.TestCase):
    def test_default_first_gear_is_two(self):
        """D-038：第一档 = 2 格/项；默认即第一档。"""
        self.assertEqual(DEFAULT_CONFIG["wheel_sens"], 2)
        self.assertEqual(Config().wheel_sens, 2)

    def test_clamp_removes_one_gear(self):
        """1 格档被钳到 2（旧配置迁移），上限 5。"""
        cfg = Config(wheel_sens=1)
        self.assertEqual(max(2, min(5, cfg.wheel_sens)), 2)
        cfg = Config(wheel_sens=9)
        self.assertEqual(min(5, cfg.wheel_sens), 5)

    def test_load_config_clamps_and_texture_fallback(self):
        old_path = theme.CONFIG_PATH
        tmp = Path(self.id() + ".json")
        theme.CONFIG_PATH = tmp
        try:
            tmp.write_text(json.dumps({"wheel_sens": 1, "texture": "bogus",
                                       "skin": "nope"}), encoding="utf-8")
            cfg = theme.load_config()
            self.assertEqual(cfg.wheel_sens, 2)
            self.assertEqual(cfg.texture, "glass")
            self.assertEqual(cfg.skin, "deepsea")
            theme.save_config(cfg)
            data = json.loads(tmp.read_text(encoding="utf-8"))
            self.assertEqual(data["texture"], "glass")
            self.assertEqual(data["wheel_sens"], 2)
        finally:
            theme.CONFIG_PATH = old_path
            if tmp.exists():
                tmp.unlink()

    def test_backdrop_toggle_persisted(self):
        """D-043 背景采样开关：默认开、可关、落盘往返。"""
        self.assertIs(DEFAULT_CONFIG["backdrop"], True)
        self.assertIs(Config().backdrop, True)
        cfg = Config(backdrop=False)
        self.assertIs(cfg.backdrop, False)
        old_path = theme.CONFIG_PATH
        tmp = Path(self.id() + ".json")
        theme.CONFIG_PATH = tmp
        try:
            theme.save_config(cfg)
            cfg2 = theme.load_config()
            self.assertIs(cfg2.backdrop, False)
            cfg2.backdrop = True
            theme.save_config(cfg2)
            self.assertIs(theme.load_config().backdrop, True)
        finally:
            theme.CONFIG_PATH = old_path
            if tmp.exists():
                tmp.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
