# -*- mode: python ; coding: utf-8 -*-
"""MousePinyin.spec —— T-021 打包配置（PyInstaller onedir 目录模式）

形态：dist/MousePinyin/MousePinyin.exe + _internal/（zip 便携分发）
- 只读词库（data/index.db + 4 个 json）随包收集到 _internal/data，
  运行时经 core/app_paths.resource_dir()（sys._MEIPASS）读取；
- 可写数据（config.json / logs）在 exe 旁（app_dir()），便携解压即可写；
- excludes 排除 PySide6 未用大件（WebEngine/Qml/Quick/3D/Pdf/Multimedia/…）
  与产品未用的 QtOpenGL/QtOpenGLWidgets（仅 spikes 使用）。
"""

a = Analysis(
    ["demo_main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("data/index.db", "data"),
        ("data/assoc.json", "data"),
        ("data/candidates.json", "data"),
        ("data/final_weights.json", "data"),
        ("data/syllables.json", "data"),
    ],
    hiddenimports=[
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "comtypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PySide6 未用大件
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
        "PySide6.QtQuickWidgets", "PySide6.QtQuickControls2",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtGraphs",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetwork", "PySide6.QtNetworkAuth",
        "PySide6.QtPositioning", "PySide6.QtLocation",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtBluetooth",
        "PySide6.QtNfc", "PySide6.QtTextToSpeech",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine",
        "PySide6.QtWebSockets", "PySide6.QtTest", "PySide6.QtDesigner",
        "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtDBus",
        # 产品代码未用（仅 spikes 使用 GL）
        "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets",
        # 无关库
        "tkinter", "numpy", "matplotlib", "PIL",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MousePinyin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI：无控制台黑窗（崩溃走 logs/stderr.log）
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MousePinyin",
)
