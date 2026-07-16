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

fluxhound.ico and theme.json, by contrast, ARE bundled as data files (datas=
below) - both are internal resources (window/taskbar icon, the CTk colour
theme), not user-facing assets someone would want to swap next to the exe, so
src/gui/theme.py resolves them relative to sys._MEIPASS when frozen instead.
icon= additionally embeds fluxhound.ico into the exe's own Win32 resources,
for Explorer/taskbar/pinned-shortcut icons shown before the app ever runs -
a separate mechanism from the runtime iconbitmap() call theme.apply_icon()
makes for each window's title bar.
"""

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# rapidocr_onnxruntime's own bundled ONNX models + config.yaml files (Gaming
# Mode's OCR detection mode - src/screen/ocr_reader.py) aren't picked up by
# PyInstaller automatically, since the package resolves them relative to its
# own installed location at runtime rather than importing them as Python
# modules. pyinstaller-hooks-contrib already has stdhooks for onnxruntime and
# cv2 themselves (their own native binaries), so those don't need handling
# here - just rapidocr's own data files.
rapidocr_datas = collect_data_files('rapidocr_onnxruntime')

# rapidocr's RapidOCR.__init__ loads its detector/classifier/recognizer via
# importlib.import_module() using *bare* module names (e.g. "ch_ppocr_v3_det",
# not "rapidocr_onnxruntime.ch_ppocr_v3_det") after appending its own
# directory to sys.path - that resolves fine from a normal pip install, but
# fails once frozen with "module 'ch_ppocr_v3_det' has no attribute
# 'TextDetector'" (verified directly - see ARCHITECTURE.md). hiddenimports
# below makes sure PyInstaller actually bundles these submodules (its static
# analysis can't trace a dynamic importlib.import_module call), and
# pyinstaller_rthook_rapidocr.py registers them under the bare names
# rapidocr's own import call expects, before the app's own code runs.
rapidocr_hidden_imports = [
    'rapidocr_onnxruntime.ch_ppocr_v3_det',
    'rapidocr_onnxruntime.ch_ppocr_v3_rec',
    'rapidocr_onnxruntime.ch_ppocr_v2_cls',
]

a = Analysis(
    ['src/main.py'],
    pathex=['.'],
    binaries=[],
    # Both land at the bundle root (sys._MEIPASS) when frozen - matches
    # src/gui/theme.py's _repo_root()/_theme_dir() resolution exactly.
    datas=[('fluxhound.ico', '.'), ('src/gui/theme.json', '.')] + rapidocr_datas,
    hiddenimports=rapidocr_hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['pyinstaller_rthook_rapidocr.py'],
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
    icon='fluxhound.ico',
)
