"""FluxHound entry point."""
from __future__ import annotations

from src.gui.main_window import MainWindow


def main() -> None:
    """Launch the FluxHound GUI application."""
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
