"""System tray icon (Windows only): lets the main window hide to the tray
instead of quitting on close, with "Show FluxHound" / "Quit" from a
right-click menu.

Built directly against the Win32 Shell_NotifyIcon API via pywin32
(win32gui.LoadImage loads fluxhound.ico straight from its file path) rather
than pystray, whose public API hard-requires a PIL.Image.Image - this app has
deliberately avoided Pillow everywhere else (the .ico itself was hand-built
via struct for the same reason), so pulling it in just for a tray icon wasn't
worth it.

Runs its own Win32 message pump on a dedicated daemon thread (matching
pywin32's own systray demo, which blocks on PumpMessages()) instead of trying
to interleave a second message source into Tkinter's own mainloop. on_show/
on_quit are always invoked via root.after(0, ...), the same pattern this app
already uses elsewhere (see DeviceConfigDialog._run_scan) to hand a
background-thread callback safely back to the Tk thread.
"""
from __future__ import annotations

import sys
import threading
from typing import Callable

_WIN32_AVAILABLE = False
if sys.platform == "win32":
    try:
        import win32api
        import win32con
        import win32gui

        _WIN32_AVAILABLE = True
    except ImportError:
        pass

_MENU_ID_SHOW = 1
_MENU_ID_QUIT = 2


class TrayIcon:
    """A best-effort tray icon: if pywin32 isn't available, or the icon fails
    to load, this quietly does nothing and is_available stays False - callers
    must check is_available before relying on the tray as the only way back
    to the window (see MainWindow._on_close)."""

    def __init__(self, root, icon_path: str, tooltip: str,
                 on_show: Callable[[], None], on_quit: Callable[[], None]):
        self._root = root
        self._icon_path = icon_path
        self._tooltip = tooltip
        self._on_show = on_show
        self._on_quit = on_quit
        self._hwnd: int | None = None
        self._icon_added = False
        if not _WIN32_AVAILABLE:
            return
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def is_available(self) -> bool:
        return _WIN32_AVAILABLE and self._icon_added

    def _run(self) -> None:
        try:
            message_map = {
                win32con.WM_DESTROY: self._on_destroy,
                win32con.WM_COMMAND: self._on_command,
                win32con.WM_USER + 20: self._on_notify,
            }
            window_class = win32gui.WNDCLASS()
            hinst = window_class.hInstance = win32api.GetModuleHandle(None)
            window_class.lpszClassName = "FluxHoundTrayWindow"
            window_class.lpfnWndProc = message_map
            class_atom = win32gui.RegisterClass(window_class)
            self._hwnd = win32gui.CreateWindow(
                class_atom, "FluxHoundTray", 0, 0, 0, 0, 0, 0, 0, hinst, None
            )
            win32gui.UpdateWindow(self._hwnd)

            hicon = win32gui.LoadImage(
                0, self._icon_path, win32con.IMAGE_ICON, 16, 16, win32con.LR_LOADFROMFILE
            )
            flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            win32gui.Shell_NotifyIcon(
                win32gui.NIM_ADD, (self._hwnd, 0, flags, win32con.WM_USER + 20, hicon, self._tooltip)
            )
            self._icon_added = True
        except Exception:
            return
        win32gui.PumpMessages()

    def _on_notify(self, hwnd, msg, wparam, lparam) -> int:
        if lparam in (win32con.WM_LBUTTONUP, win32con.WM_LBUTTONDBLCLK):
            self._root.after(0, self._on_show)
        elif lparam == win32con.WM_RBUTTONUP:
            self._show_menu()
        return 0

    def _show_menu(self) -> None:
        menu = win32gui.CreatePopupMenu()
        win32gui.AppendMenu(menu, win32con.MF_STRING, _MENU_ID_SHOW, "Show FluxHound")
        win32gui.AppendMenu(menu, win32con.MF_STRING, _MENU_ID_QUIT, "Quit")
        pos = win32gui.GetCursorPos()
        win32gui.SetForegroundWindow(self._hwnd)
        win32gui.TrackPopupMenu(menu, win32con.TPM_LEFTALIGN, pos[0], pos[1], 0, self._hwnd, None)
        win32gui.PostMessage(self._hwnd, win32con.WM_NULL, 0, 0)

    def _on_command(self, hwnd, msg, wparam, lparam) -> int:
        item_id = win32api.LOWORD(wparam)
        if item_id == _MENU_ID_SHOW:
            self._root.after(0, self._on_show)
        elif item_id == _MENU_ID_QUIT:
            self._root.after(0, self._on_quit)
        return 0

    def _on_destroy(self, hwnd, msg, wparam, lparam) -> int:
        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (self._hwnd, 0))
        win32gui.PostQuitMessage(0)
        return 0

    def remove(self) -> None:
        """Tear down the tray icon and stop its message loop. Call once,
        when the app is actually quitting (not on every hide-to-tray)."""
        if not _WIN32_AVAILABLE or self._hwnd is None:
            return
        win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
