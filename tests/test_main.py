"""Unit test for src.main's KeyboardInterrupt handling - the GUI/mainloop
itself isn't unit-testable, so MainWindow is mocked; this only checks the
control flow around it."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import src.main as main_module


def test_keyboard_interrupt_from_mainloop_triggers_a_clean_quit():
    """Regression test for a real report: Ctrl+C in a console raises
    KeyboardInterrupt straight out of Tcl's mainloop callback dispatch, with
    nothing catching it - the process died immediately, skipping every
    cleanup path a normal window close goes through (stopping an active
    reactive mode, flushing an in-progress --debug log, removing the tray
    icon). main() must catch it and call the app's real shutdown path."""
    fake_app = MagicMock()
    fake_app.mainloop.side_effect = KeyboardInterrupt()

    with patch.object(main_module, "MainWindow", return_value=fake_app), \
         patch.object(main_module, "theme"), \
         patch.object(main_module, "_enable_dpi_awareness"), \
         patch("sys.argv", ["main.py"]):
        main_module.main()  # must not let KeyboardInterrupt propagate uncaught

    assert fake_app.mainloop.called
    assert fake_app._quit.called
