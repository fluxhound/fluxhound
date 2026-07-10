"""Manual control mode: direct user control of a single bulb."""
from __future__ import annotations

from src.tuya.device import TuyaBulb


class ManualMode:
    """Lets the user directly control one bulb (on/off, white, colour)."""

    def __init__(self, bulb: TuyaBulb):
        self.bulb = bulb

    def toggle(self, on: bool) -> None:
        """Turn the bulb on or off."""
        if on:
            self.bulb.turn_on()
        else:
            self.bulb.turn_off()
