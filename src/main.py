"""FluxHound entry point."""
from __future__ import annotations

from src.gui.main_window import MainWindow
from src.tuya.device import TuyaBulb

try:
    from src import local_config as cfg
except ImportError:
    cfg = None


def build_bulb() -> TuyaBulb | None:
    """Create a TuyaBulb from local_config.py, or None if it is not present."""
    if cfg is None:
        return None
    return TuyaBulb(cfg.DEVICE_ID, cfg.IP_ADDRESS, cfg.LOCAL_KEY, version=cfg.PROTOCOL_VERSION)


def main() -> None:
    """Launch the FluxHound GUI application."""
    bulb = build_bulb()
    app = MainWindow(bulb)
    app.mainloop()


if __name__ == "__main__":
    main()
