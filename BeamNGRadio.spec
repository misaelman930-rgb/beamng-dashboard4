# -*- mode: python ; coding: utf-8 -*-
# Сборка: из папки проекта выполните  python -m PyInstaller BeamNGRadio.spec --noconfirm
# (build.bat делает это автоматически)
from PyInstaller.utils.hooks import collect_submodules

# pynput подгружает бэкенд (Windows) динамически — PyInstaller этого не видит, добавляем вручную.
HIDDEN = collect_submodules("pynput")

# Тяжёлые модули Qt, которые приложение не использует. Исключение уменьшает .exe в несколько раз.
EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DExtras", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "tkinter", "beamngpy", "server",
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    # страницы панели (cluster.html, digital.html) обязательно нужны в .exe;
    # libvlc НЕ кладём: приложение берёт VLC, установленный на ПК
    datas=[("radio/static", "radio/static")],
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BeamNGRadio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # окно без консоли; ошибки показываются через MessageBox и crash.log
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BeamNGRadio",
)
