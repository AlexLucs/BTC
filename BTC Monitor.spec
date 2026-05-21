# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['BTC Monitor.py'],
    pathex=[],
    binaries=[('C:\\Users\\Tera\\AppData\\Local\\Programs\\Python\\Python313\\python313.dll', '.')],
    datas=[('index.html', '.'), ('jquery-confirm.min.js', '.'), ('jquery-confirm.min.css', '.'), ('jquery.min.js', '.'), ('Roboto.woff2', '.'), ('btc-logo.svg', '.'), ('alerta.mp3', '.'), ('script.js', '.'), ('style.css', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [('O', None, 'OPTION')],
    exclude_binaries=True,
    name='BTC Monitor',
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
    icon=['btc-logo.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BTC Monitor',
)
