"""ui/theme.py —— 皮肤系统 + 质感系统 + 配置管理（D-022/D-038）

皮肤 = 键帽配色方案（液态玻璃渲染参数化，透明玻璃皮肤 trans>0）；
质感 = 玻璃渲染风格四档（素面/玻璃/磨砂/棱镜：色散相差/折射/流光/厚度/受光）；
配置持久化 data/config.json：skin / texture / font_size / scale / glass /
wheel_sens（2~5 格每项，第一档=2；1 格档在高滚轮密度下会双跳，已移除）/ pos。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from core.app_paths import app_dir

CONFIG_PATH = app_dir() / "data" / "config.json"


@dataclass
class Skin:
    key: str
    name: str
    cap_top: str        # 键帽渐变顶色
    cap_bottom: str     # 键帽渐变底色
    cap_border: str     # 键帽描边
    text: str           # 普通键帽文字
    text_dim: str       # 远处键帽文字（衰减后仍受 alpha 控制）
    accent: str         # 选中键帽底色
    accent_text: str    # 选中文字
    trans: float = 0.0  # 透明玻璃度 0~1（>0 = 透明玻璃皮肤：键帽/底框按比例透出桌面）


SKINS: dict[str, Skin] = {
    "deepsea": Skin("deepsea", "深海玻璃",
                    "#2a3a5e", "#16203a", "#4a5f8a", "#c8d2ee", "#7a86a8",
                    "#534AB7", "#ffffff"),
    "mist":    Skin("mist", "晨雾白",
                    "#f7f9fc", "#dfe5ef", "#b8c2d4", "#2a3040", "#8a93a8",
                    "#5b52d6", "#ffffff"),
    "amethyst": Skin("amethyst", "紫晶",
                     "#3a2d5c", "#241a3a", "#6a5590", "#e2d8ff", "#9a8cc0",
                     "#7c5cff", "#ffffff"),
    "jade":    Skin("jade", "翡翠",
                    "#1c4a38", "#0e2c20", "#3d7a5e", "#c0f0da", "#6a9a84",
                    "#1d9e75", "#ffffff"),
    "gold":    Skin("gold", "暗金",
                    "#4a3c1e", "#2c2410", "#8a7440", "#f0e2b8", "#a89468",
                    "#c89b3c", "#2a2210"),
    # ---- D-038 新增皮肤（前 3 款为透明玻璃）----
    "air":     Skin("air", "空气玻璃",
                    "#eaf2fb", "#cdd9ea", "#aebfd8", "#1f2a3a", "#5a6478",
                    "#4f8ef7", "#ffffff", 0.45),
    "ice":     Skin("ice", "冰晶玻璃",
                    "#d9f3fb", "#b5dff0", "#9cc8e0", "#123a4a", "#6a94a8",
                    "#22a7d8", "#ffffff", 0.50),
    "rose":    Skin("rose", "薄暮玫瑰",
                    "#fbe4ef", "#eec3dc", "#d8a8c4", "#3a1f2e", "#a87890",
                    "#e0568f", "#ffffff", 0.40),
    "graphite": Skin("graphite", "石墨",
                     "#3a3f47", "#23262c", "#565c66", "#dfe3ea", "#8a90a0",
                     "#7aa2f7", "#0e1014", 0.15),
    "aurora":  Skin("aurora", "极光",
                    "#16324a", "#0c1f33", "#2e6a5e", "#d4f4ea", "#7aa898",
                    "#2dd4a7", "#06231a", 0.35),
}


@dataclass(frozen=True)
class Texture:
    key: str
    name: str
    dispersion: float   # 色散（相差）：边缘青/红双描边强度 0~1
    refract: float      # 折射：内弯高光线（厚玻璃弯曲感）0~1
    sheen: float        # 内页流光：顶部高光/斜光带强度 0~1
    depth: float        # 内页厚度：底部内阴影 + 环境倒影带 0~1
    light_gain: float   # 光标光源照亮玻璃边缘的增益 0~1.3


TEXTURES: dict[str, Texture] = {
    "plain":   Texture("plain", "素面", 0.0, 0.0, 0.35, 0.25, 0.0),
    "glass":   Texture("glass", "玻璃", 0.5, 0.6, 1.0, 0.7, 1.0),
    "frosted": Texture("frosted", "磨砂", 0.15, 0.25, 0.5, 0.9, 0.35),
    "prism":   Texture("prism", "棱镜", 1.0, 1.0, 1.0, 0.8, 1.25),
}


DEFAULT_CONFIG = {
    "skin": "deepsea",
    "texture": "glass",  # 质感：plain 素面 / glass 玻璃 / frosted 磨砂 / prism 棱镜
    "font_size": 20,     # 键帽主字号 px
    "scale": 1.0,        # 整体缩放 0.7~1.5
    "glass": 0.8,        # 液态玻璃强度 0~1（0=纯色不透明）
    "wheel_sens": 2,     # 滚轮灵敏度：第一档=2 格/项（1 格档高密度滚轮下双跳，D-038 移除）
    "backdrop": True,    # D-043 玻璃背景采样（透明皮肤折射真实背景；关闭回退平涂）
    "three_key": False,  # D-049 三键模式（无侧键）：右键=逐字退格，选韵头即上屏
    "x": None,           # 位置（None = 默认吸底居中）
    "y": None,
}


@dataclass
class Config:
    skin: str = "deepsea"
    texture: str = "glass"
    font_size: int = 20
    scale: float = 1.0
    glass: float = 0.8
    wheel_sens: int = 2
    backdrop: bool = True
    three_key: bool = False
    x: int | None = None
    y: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def skin_obj(self) -> Skin:
        return SKINS.get(self.skin, SKINS["deepsea"])

    @property
    def texture_obj(self) -> Texture:
        return TEXTURES.get(self.texture, TEXTURES["glass"])


def load_config() -> Config:
    cfg = Config()
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k in ("skin", "texture", "font_size", "scale", "glass",
                      "wheel_sens", "backdrop", "three_key", "x", "y"):
                if k in data:
                    setattr(cfg, k, data[k])
            cfg.extra = {k: v for k, v in data.items()
                         if k not in ("skin", "texture", "font_size", "scale",
                                      "glass", "wheel_sens", "backdrop",
                                      "three_key", "x", "y")}
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    # 边界钳制（D-038：滚轮第一档=2 格/项，1 格档双跳移除）
    cfg.font_size = max(14, min(28, int(cfg.font_size)))
    cfg.scale = max(0.7, min(1.5, float(cfg.scale)))
    cfg.glass = max(0.0, min(1.0, float(cfg.glass)))
    cfg.wheel_sens = max(2, min(5, int(cfg.wheel_sens)))
    cfg.backdrop = bool(cfg.backdrop)
    cfg.three_key = bool(cfg.three_key)
    if cfg.skin not in SKINS:
        cfg.skin = "deepsea"
    if cfg.texture not in TEXTURES:
        cfg.texture = "glass"
    return cfg


def save_config(cfg: Config) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {"skin": cfg.skin, "texture": cfg.texture,
                "font_size": cfg.font_size, "scale": cfg.scale,
                "glass": cfg.glass, "wheel_sens": cfg.wheel_sens,
                "backdrop": cfg.backdrop, "three_key": cfg.three_key,
                "x": cfg.x, "y": cfg.y, **cfg.extra}
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
