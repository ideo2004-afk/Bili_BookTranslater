# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=[('icons', 'icons'), ('gui/styles', 'gui/styles'), ('prompt_學術.json', '.'), ('prompt_繁中.json', '.'), ('prompt_通用.json', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Remove googleapiclient discovery cache to save space (~76MB)
a.datas = [d for d in a.datas if "googleapiclient/discovery_cache" not in d[0]]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Bili',
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
    icon=['/Users/ideo2004/Bili/icons/logo.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Bili',
)
app = BUNDLE(
    coll,
    name='Bili.app',
    icon='/Users/ideo2004/Bili/icons/logo.icns',
    bundle_identifier=None,
)
