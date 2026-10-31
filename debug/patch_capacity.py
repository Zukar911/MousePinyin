# -*- coding: utf-8 -*-
"""dock_strip 收尾：容量字段 init + grow 常量包络 + _layout_base 容量基准 x0。"""
from pathlib import Path

p = Path("ui/dock_strip.py")
t = p.read_text(encoding="utf-8")

pairs = [
    # __init__ 字段
    ('        self._backdrop = None           # D-042 背景折射源（窗口采样器注入）\n',
     '        self._backdrop = None           # D-042 背景折射源（窗口采样器注入）\n'
     '        self._units_capacity = 0.0      # D-050 容量包络：历史最宽层的键帽总量 U\n'
     '        self._n_capacity = 0            # D-050 容量包络：历史最多项数\n'),
    # grow 常量包络（两处）
    ('        grow = self._e_units_capacity * u + 0.45 * u + 8.0\n'
     '        gap_total = self._gap * (self._n_capacity - 1)\n',
     '        grow = 3.0 * u + 8.0            # 鼓包能量包络（≈2.65U 上界）+ 端部余量\n'
     '        gap_total = self._gap * (self._n_capacity - 1)\n'),
]
for old, new in pairs:
    assert old in t, f"锚点未命中: {old[:50]!r}"
    t = t.replace(old, new, 1)

# 定点迭代内的 grow（第一处已被第二条覆盖到 setFixedWidth 前——再查迭代内）
old_it = """        for _ in range(60):                    # 定点迭代（开销随最终 u 取值）
            gap = max(4.0, u * 0.15)
            pad = max(94.0, u * 2.4)
            grow = self._e_units_capacity * u + 0.45 * u + 8.0"""
new_it = """        for _ in range(60):                    # 定点迭代（开销随最终 u 取值）
            gap = max(4.0, u * 0.15)
            pad = max(94.0, u * 2.4)
            grow = 3.0 * u + 8.0               # 鼓包包络常量（与 setFixedWidth 一致）"""
assert old_it in t, "迭代内 grow 锚点未命中"
t = t.replace(old_it, new_it, 1)

# _layout_base x0 容量基准（层级间恒定）
old_x0 = """        self._e_ref = self._energy_units(n // 2) * self._u
        base_w = [cap_units(x) * self._u for x in self._items]
        row_w = sum(base_w) + self._gap * (n - 1)
        avail = self.width() - self._pad_r
        grow = self._e_ref + 0.45 * self._u + 8.0
        self._x0 = max(8.0, (avail - row_w - grow) / 2.0)"""
new_x0 = """        self._e_ref = self._energy_units(n // 2) * self._u
        base_w = [cap_units(x) * self._u for x in self._items]
        # D-050：x0 由**容量包络**决定（配置不变则恒定）——层级切换时键帽
        # 左缘不动、右侧留白给 ⚙/✕；窄层的鱼眼鼓包向右伸入留白区
        row_w_cap = (self._units_capacity * self._u
                     + (self._n_capacity - 1) * self._gap)
        grow_cap = 3.0 * self._u + 8.0
        avail = self.width() - self._pad_r
        self._x0 = max(8.0, (avail - row_w_cap - grow_cap) / 2.0)
        row_w = sum(base_w) + self._gap * (n - 1)   # （保留语义注释占位）"""
assert old_x0 in t, "_layout_base 锚点未命中"
t = t.replace(old_x0, new_x0, 1)

p.write_text(t, encoding="utf-8")
import ast
ast.parse(t)
print("dock_strip capacity patches OK")
