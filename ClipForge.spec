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
    (str(project_root / 'resources' / 'badges'), 'resources/badges'),
]

added_binaries = []
ffmpeg_exe = project_root / 'bin' / 'ffmpeg.exe'
if ffmpeg_exe.is_file():
    added_binaries.append((str(ffmpeg_exe), 'bin'))

common_hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PIL',
    'PIL.Image',
    'imageio_ffmpeg',
    'cv2',
    'numpy',
]

common_excludes = ['matplotlib', 'tkinter', 'test', 'unittest', 'notebook', 'IPython']

# 1. Main Application (ClipForge 3.0 Full Suite)
a1 = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=added_binaries,
    datas=added_files,
    hiddenimports=common_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=common_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 2. Standalone Color Matrix Studio Runner
a2 = Analysis(
    ['run_color_matrix.py'],
    pathex=['.'],
    binaries=added_binaries,
    datas=added_files,
    hiddenimports=common_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=common_excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz1 = PYZ(a1.pure, a1.zipped_data, cipher=block_cipher)
pyz2 = PYZ(a2.pure, a2.zipped_data, cipher=block_cipher)

exe1 = EXE(
    pyz1,
    a1.scripts,
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

exe2 = EXE(
    pyz2,
    a2.scripts,
    [],
    exclude_binaries=True,
    name='ClipForge_ColorMatrix',
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
    exe1,
    exe2,
    a1.binaries + a2.binaries,
    a1.zipfiles + a2.zipfiles,
    a1.datas + a2.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ClipForge',
)
