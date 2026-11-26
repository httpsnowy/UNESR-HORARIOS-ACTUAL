# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [('C:/Users/ornel/OneDrive/Desktop/UNESR_Horarios-main/app/templates', 'app/templates'), ('C:/Users/ornel/OneDrive/Desktop/UNESR_Horarios-main/assets', 'assets'), ('C:/Users/ornel/OneDrive/Desktop/UNESR_Horarios-main/data', 'data'), ('C:/Users/ornel/OneDrive/Desktop/UNESR_Horarios-main/uploads', 'uploads'), ('C:/Users/ornel/OneDrive/Desktop/UNESR_Horarios-main/.env.example', '.')]
datas += collect_data_files('webview')


a = Analysis(
    ['C:/Users/ornel/OneDrive/Desktop/UNESR_Horarios-main/main.py'],
    pathex=['C:/Users/ornel/OneDrive/Desktop/UNESR_Horarios-main'],
    binaries=[],
    datas=datas,
    hiddenimports=['webview', 'httpx', 'openpyxl', 'webview.platforms.gtk', 'webview.platforms.qt', 'webview.platforms.winforms'],
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
    name='UNESR_Horarios',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='UNESR_Horarios',
)
