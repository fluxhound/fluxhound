"""PyInstaller runtime hook: rapidocr_onnxruntime's own RapidOCR.__init__
does `sys.path.append(str(Path(__file__).resolve().parent))` and then
`importlib.import_module("ch_ppocr_v3_det")` (a *bare* name, not
"rapidocr_onnxruntime.ch_ppocr_v3_det") - it's relying on its own directory
being a real filesystem path with sys.path-based import resolution. That's
true for a normal pip install, but not once frozen: __file__ then resolves
inside PyInstaller's own bundle, where sys.path-based file lookups for
already-bundled code don't apply the same way, so the bare import fails with
"module 'ch_ppocr_v3_det' has no attribute 'TextDetector'" (a real, verified
failure - see ARCHITECTURE.md).

Fix: import each submodule through its real, PyInstaller-resolvable
qualified name (rapidocr_onnxruntime.ch_ppocr_v3_det, ...; these must also be
listed in fluxhound.spec's hiddenimports, since PyInstaller's static
analysis can't trace rapidocr's dynamic importlib.import_module call to know
to bundle them at all) and register them into sys.modules under the bare
names rapidocr's own import_module call expects - Python's import system
checks sys.modules before doing any path-based resolution, so this fully
satisfies that call without needing sys.path to behave the way rapidocr
assumed.
"""
import sys

import rapidocr_onnxruntime.ch_ppocr_v2_cls
import rapidocr_onnxruntime.ch_ppocr_v3_det
import rapidocr_onnxruntime.ch_ppocr_v3_rec

sys.modules["ch_ppocr_v3_det"] = rapidocr_onnxruntime.ch_ppocr_v3_det
sys.modules["ch_ppocr_v3_rec"] = rapidocr_onnxruntime.ch_ppocr_v3_rec
sys.modules["ch_ppocr_v2_cls"] = rapidocr_onnxruntime.ch_ppocr_v2_cls
