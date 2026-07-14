# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build config for a single portable FluxHound.exe.

Build with: pyinstaller fluxhound.spec

fluxhound_logo.png is deliberately NOT bundled as a PyInstaller data file -
MainWindow._app_root_dir() resolves it relative to sys.executable (the built
.exe's own directory) when frozen, matching every other local config file's
"lives next to the portable exe" convention, not PyInstaller's onefile temp
extraction dir (sys._MEIPASS). Copy fluxhound_logo.png into dist/ alongside
the built exe after building (see README's build instructions) - the app
runs fine without it too, just without the logo overlay on the live-state
indicator.
"""

block_cipher = None

a = Analysis(
    ['src/main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FluxHound',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
