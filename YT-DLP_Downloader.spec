# -*- mode: python ; coding: utf-8 -*-
import sys

ffmpeg_data = []
if sys.platform == "win32":
    ffmpeg_data.append(('bin/ffmpeg.exe', 'bin/'))
else:
    ffmpeg_data.append(('bin/ffmpeg', 'bin/'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=ffmpeg_data + [
        ('YDD.icon/icon.ico', 'YDD.icon/'),
        ('YDD.icon/Assets/square.and.arrow.down.fill.png', 'YDD.icon/Assets/'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='YT-DLP_Downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='YDD.icon/icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='YT-DLP_Downloader',
)
