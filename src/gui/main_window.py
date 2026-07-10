"""Main application window (customtkinter)."""
from __future__ import annotations

import customtkinter as ctk

from src.tuya.device import TuyaBulb


class MainWindow(ctk.CTk):
    """FluxHound main window: lets the user switch a single test bulb on/off."""

    def __init__(self, bulb: TuyaBulb | None):
        super().__init__()
        self.bulb = bulb

        self.title("FluxHound")
        self.geometry("360x220")

        status_text = "No device configured (see src/local_config.py.example)" if bulb is None else "Device ready"
        self.status_label = ctk.CTkLabel(self, text=status_text, wraplength=320)
        self.status_label.pack(pady=20)

        button_state = "normal" if bulb is not None else "disabled"
        self.on_button = ctk.CTkButton(self, text="On", command=self._turn_on, state=button_state)
        self.on_button.pack(pady=5)

        self.off_button = ctk.CTkButton(self, text="Off", command=self._turn_off, state=button_state)
        self.off_button.pack(pady=5)

    def _turn_on(self) -> None:
        """Handle a click on the On button."""
        self.bulb.turn_on()
        self.status_label.configure(text="Bulb switched on")

    def _turn_off(self) -> None:
        """Handle a click on the Off button."""
        self.bulb.turn_off()
        self.status_label.configure(text="Bulb switched off")
