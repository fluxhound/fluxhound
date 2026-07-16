"""FluxHound entry point."""
from __future__ import annotations

import argparse
import sys

from src.gui import theme
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FluxHound")
    parser.add_argument(
        "--debug", action="store_true",
        help="Log Audio Mode's raw timbre/energy/beat signal to a timestamped CSV "
             "(audio_debug_<timestamp>.csv, next to the app) every time it's activated, "
             "for reviewing a calibration pass against real music afterward.",
    )
    return parser.parse_args()


def main() -> None:
    """Launch the FluxHound GUI application."""
    args = _parse_args()
    _enable_dpi_awareness()
    theme.apply()  # must run before the first CTk widget is constructed
    app = MainWindow(debug=args.debug)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        # Ctrl+C in a console raises KeyboardInterrupt straight out of Tcl's
        # mainloop callback dispatch - nothing else in the call stack catches
        # it, so without this the process dies immediately, skipping every
        # cleanup path a normal window close goes through: stopping an
        # active reactive mode's background thread/bulb connection, flushing
        # an in-progress --debug log (a real report showed a log's last
        # session losing every row because of this), removing the tray icon.
        # _quit() is the exact same real-shutdown path the tray icon's own
        # "Quit" entry already uses - mainloop() returning/raising doesn't
        # tear down the underlying Tk interpreter, so it's still safe to call.
        app._quit()


if __name__ == "__main__":
    main()
