# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

block_cipher = None
project_root = Path('.').resolve()

added_files = [
    (str(project_root / 'resources' / 'icons'), 'resources/icons'),
    (str(project_root / 'resources' / 'styles'), 'resources/styles'),
    (str(project_root / 'resources' / 'templates'), 'resources/templates'),
    (str(project_root / 'resources' / 'fonts'), 'resources/fonts'),
]

added_binaries = []
ffmpeg_exe = project_root / 'bin' / 'ffmpeg.exe'
if ffmpeg_exe.is_file():
    added_binaries.append((str(ffmpeg_exe), 'bin'))

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=added_binaries,
    datas=added_files,
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PIL',
        'PIL.Image',
        'imageio_ffmpeg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'test', 'unittest', 'notebook', 'IPython'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ClipForge',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / 'resources' / 'icons' / 'logo.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ClipForge',
)
