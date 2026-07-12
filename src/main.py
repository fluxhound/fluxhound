"""FluxHound entry point."""
from __future__ import annotations

import sys

from src.gui.main_window import MainWindow


def _enable_dpi_awareness() -> None:
    """Mark this process per-monitor DPI aware before any Tk window is created.

    Without this, Windows virtualizes Tkinter's screen coordinates when display
    scaling isn't 100%, so geometry()/winfo_* stop matching the physical pixel
    coordinates mss (Ambience Mode's screen capture) works in - the region
    selector's drag rectangle would then land in the wrong place relative to what
    actually gets captured. Best-effort: harmless if it fails (e.g. non-Windows).
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        pass


def main() -> None:
    """Launch the FluxHound GUI application."""
    _enable_dpi_awareness()
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
