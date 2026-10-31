"""ui/settings_dialog.py —— 设置界面（D-022 UI 系统 + D-038 皮肤×10/质感四档/滚轮 2~5）

内容：皮肤十选一（网格）/ 质感四选一（素面/玻璃/磨砂/棱镜）/ 字体大小
14~28 / 整体大小 0.7×~1.5× / 液态玻璃强度 0~1 / 滚轮灵敏度 2~5 格每项
（第一档=2 格/项，D-038：1 格档在高密度滚轮下会一次跳两项，已移除），
全部**实时应用**（滑条一动即回调 on_change(cfg)，由 candidate_window 落盘
+重绘），"完成"只关窗。恢复默认 = 一键回出厂参数。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QToolButton,
                               QVBoxLayout)

from ui.theme import DEFAULT_CONFIG, SKINS, TEXTURES, Config


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg: Config, on_change):
        super().__init__(parent)
        self.setWindowTitle("鼠标拼音输入 · 设置")
        self.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        self._cfg = cfg
        self._on_change = on_change
        self._busy = False
        self.setFixedWidth(380)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # ---- 皮肤（10 款，网格 5×2；D-038）----
        lay.addWidget(QLabel("皮肤"))
        grid = QGridLayout()
        grid.setSpacing(6)
        self._skin_btns: dict[str, QToolButton] = {}
        for idx, (key, sk) in enumerate(SKINS.items()):
            b = QToolButton()
            b.setText(sk.name)
            b.setCheckable(True)
            b.setFixedSize(64, 40)
            b.setToolTip("透明玻璃皮肤" if getattr(sk, "trans", 0) > 0 else "")
            b.setStyleSheet(
                f"QToolButton{{background:{sk.cap_bottom};color:{sk.text};"
                f"border:2px solid {sk.cap_border};border-radius:8px;font-size:11px;}}"
                "QToolButton:checked{border:2px solid #7aa2f7;font-weight:bold;}")
            b.clicked.connect(lambda _, k=key: self._set_skin(k))
            grid.addWidget(b, idx // 5, idx % 5)
            self._skin_btns[key] = b
        lay.addLayout(grid)

        # ---- 质感（四档，D-038：色散/折射/流光/厚度/受光）----
        lay.addWidget(QLabel("玻璃质感"))
        tex_row = QHBoxLayout()
        self._tex_btns: dict[str, QToolButton] = {}
        for key, tx in TEXTURES.items():
            b = QToolButton()
            b.setText(tx.name)
            b.setCheckable(True)
            b.setFixedSize(64, 32)
            b.setStyleSheet(
                "QToolButton{background:rgba(90,100,130,60);color:#dfe3ee;"
                "border:2px solid rgba(140,150,180,90);border-radius:8px;"
                "font-size:11px;}"
                "QToolButton:checked{border:2px solid #7aa2f7;font-weight:bold;}")
            b.clicked.connect(lambda _, k=key: self._set_texture(k))
            tex_row.addWidget(b)
            self._tex_btns[key] = b
        lay.addLayout(tex_row)

        # ---- 四个滑条 ----
        self._sl_font = self._add_slider(lay, "字体大小", 14, 28, cfg.font_size,
                                         "set_font", fmt=lambda v: f"{v} px")
        self._sl_scale = self._add_slider(lay, "整体大小", 70, 150,
                                          int(cfg.scale * 100), "set_scale",
                                          fmt=lambda v: f"{v / 100:.2f} ×")
        self._sl_glass = self._add_slider(lay, "液态玻璃强度", 0, 100,
                                          int(cfg.glass * 100), "set_glass",
                                          fmt=lambda v: f"{v / 100:.2f}")
        self._sl_wheel = self._add_slider(lay, "滚轮灵敏度（越大越稳）", 2, 5,
                                          cfg.wheel_sens, "set_wheel",
                                          fmt=lambda v: f"{v} 格/项")

        # ---- D-043 背景采样开关 ----
        self._cb_backdrop = QCheckBox("玻璃背景采样（透明皮肤折射真实背景）")
        self._cb_backdrop.setChecked(cfg.backdrop)
        self._cb_backdrop.toggled.connect(self._set_backdrop)
        lay.addWidget(self._cb_backdrop)

        # ---- D-049 三键模式（无侧键用户）----
        self._cb_3k = QCheckBox("三键模式（只有滚轮+左右键：右键=逐字退格，"
                                "选韵头即上屏，无选字翻页/侧键）")
        self._cb_3k.setChecked(cfg.three_key)
        self._cb_3k.toggled.connect(self._set_three_key)
        lay.addWidget(self._cb_3k)

        # ---- 按钮 ----
        row = QHBoxLayout()
        reset = QPushButton("恢复默认")
        done = QPushButton("完成")
        done.setDefault(True)
        reset.clicked.connect(self._reset)
        done.clicked.connect(self.accept)
        row.addWidget(reset)
        row.addStretch(1)
        row.addWidget(done)
        lay.addLayout(row)
        self._sync_skin_checks()
        self._sync_texture_checks()

    # ---------- 构建滑条行 ----------

    def _add_slider(self, lay, title: str, lo: int, hi: int, val: int,
                    setter: str, fmt):
        lay.addWidget(QLabel(title))
        row = QHBoxLayout()
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)
        lb = QLabel(fmt(val))
        lb.setFixedWidth(52)
        lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        def changed(v, _s=setter, _f=fmt, _lb=lb):
            _lb.setText(_f(v))
            if self._busy:
                return
            self._apply(_s, v)

        sl.valueChanged.connect(changed)
        row.addWidget(sl)
        row.addWidget(lb)
        lay.addLayout(row)
        setattr(self, f"_sl_{setter}", sl)
        return sl

    def _apply(self, setter: str, v: int) -> None:
        if setter == "set_font":
            self._cfg.font_size = v
        elif setter == "set_scale":
            self._cfg.scale = v / 100
        elif setter == "set_glass":
            self._cfg.glass = v / 100
        elif setter == "set_wheel":
            self._cfg.wheel_sens = v
        self._on_change(self._cfg)

    # ---------- 皮肤 / 质感 / 重置 ----------

    def _set_skin(self, key: str) -> None:
        self._cfg.skin = key
        self._sync_skin_checks()
        self._on_change(self._cfg)

    def _set_texture(self, key: str) -> None:
        self._cfg.texture = key
        self._sync_texture_checks()
        self._on_change(self._cfg)

    def _set_backdrop(self, on: bool) -> None:
        self._cfg.backdrop = on
        self._on_change(self._cfg)

    def _set_three_key(self, on: bool) -> None:
        self._cfg.three_key = on
        self._on_change(self._cfg)

    def _sync_skin_checks(self) -> None:
        for k, b in self._skin_btns.items():
            b.setChecked(k == self._cfg.skin)

    def _sync_texture_checks(self) -> None:
        for k, b in self._tex_btns.items():
            b.setChecked(k == self._cfg.texture)

    def _reset(self) -> None:
        self._busy = True           # 批量回设控件时不逐值触发回调
        self._cfg.skin = DEFAULT_CONFIG["skin"]
        self._cfg.texture = DEFAULT_CONFIG["texture"]
        self._cfg.font_size = DEFAULT_CONFIG["font_size"]
        self._cfg.scale = DEFAULT_CONFIG["scale"]
        self._cfg.glass = DEFAULT_CONFIG["glass"]
        self._cfg.wheel_sens = DEFAULT_CONFIG["wheel_sens"]
        self._cfg.backdrop = DEFAULT_CONFIG["backdrop"]
        self._cfg.three_key = DEFAULT_CONFIG["three_key"]
        self._sync_skin_checks()
        self._sync_texture_checks()
        self._cb_backdrop.setChecked(self._cfg.backdrop)
        self._cb_3k.setChecked(self._cfg.three_key)
        self._sl_set_font.setValue(self._cfg.font_size)
        self._sl_set_scale.setValue(int(self._cfg.scale * 100))
        self._sl_set_glass.setValue(int(self._cfg.glass * 100))
        self._sl_set_wheel.setValue(self._cfg.wheel_sens)
        self._busy = False
        self._on_change(self._cfg)  # 一次性应用
