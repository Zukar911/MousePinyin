"""core/app_paths.py —— 应用路径定位（T-021 打包适配）

两种形态：
- 开发态：一切相对仓库根（现状不变，单测/直接跑 py 不受影响）。
- 打包态（PyInstaller onedir）：sys.frozen = True
  - resource_dir() = sys._MEIPASS（即 _internal/）——**只读资源**（词库 index.db、
    *.json 随包分发，收集时落位 _internal/data）；
  - app_dir() = exe 所在目录——**可写数据**（config.json 用户设置、logs 崩溃日志），
    放 exe 旁保证"解压即便携"（不写进 _internal，避开潜在只读安装位置）。
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """可写数据根（配置/日志）：打包态 = exe 旁；开发态 = 仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return _ROOT


def resource_dir() -> Path:
    """只读资源根（词库）：打包态 = _internal；开发态 = 仓库根。"""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else _ROOT
