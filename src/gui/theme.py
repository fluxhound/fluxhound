"""FluxHound's design system: one place every window/dialog pulls colours,
fonts, and spacing from, instead of customtkinter's generic default blue
theme or one-off literals scattered across files.

apply() must run once, before the first CTk widget is constructed (i.e.
before MainWindow()) - customtkinter's ThemeManager loads a theme globally
and every subsequently-constructed widget reads its default colours from it
at construction time. theme.json carries the actual colour values (mirrors
customtkinter's own bundled theme JSON structure, e.g. blue.json) since
set_default_color_theme only accepts a file path, not a dict.

The named constants below cover the handful of places code still needs an
explicit colour (status text, error banners, the audio-mode grid's selected-
cell highlight, secondary/destructive buttons) - kept in sync with
theme.json by hand, since customtkinter has no API to read a colour back out
of the loaded theme by name.
"""
from __future__ import annotations

import sys
from pathlib import Path

import customtkinter as ctk

# Brand: a single vivid pink/magenta accent against clean neutral chrome,
# rather than a colour derived from the logo file itself - the logo's
# apparent background in any given screenshot is just whatever colour the
# live-state glow happens to be showing at that moment, not a fixed brand
# colour (see the radial glow behind the logo in MainWindow).
PRIMARY = ("#E91E82", "#FF2D91")
PRIMARY_HOVER = ("#C21569", "#D91F79")
PRIMARY_PRESSED = ("#9E1057", "#B01868")

SECONDARY_BUTTON_COLOR = ("#8A8A90", "#3A3A42")
SECONDARY_BUTTON_HOVER_COLOR = ("#75757A", "#2E2E34")

TEXT_COLOR = ("#1A1A1E", "#F2F2F5")
TEXT_MUTED_COLOR = ("gray40", "gray65")

ERROR_COLOR = ("#B91C1C", "#F87171")
SUCCESS_COLOR = ("#15803D", "#4ADE80")

# Single literal values (not light/dark pairs) for raw tkinter.Canvas widgets,
# which don't understand CTk's (light, dark) colour-tuple convention - the app
# is dark-mode-only (see apply()), so these are just that pair's dark half.
CANVAS_BORDER_COLOR = "#3A3A42"
CANVAS_BG_COLOR = "#1B1B1F"

# PRO badge (paid-tier features) - reuses the brand accent, since "unlocking
# this gets you the vivid thing" is exactly the association the badge wants.
PRO_BADGE_COLOR = PRIMARY
PRO_BADGE_TEXT_COLOR = ("#FFFFFF", "#FFFFFF")

# Spacing scale - every window's padx/pady should be one of these instead of
# an arbitrary number, so margins actually look consistent across screens.
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_SECTION = 20

FONT_FAMILY = "Segoe UI" if sys.platform == "win32" else None  # None = CTkFont's own platform default


def _theme_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


THEME_PATH = _theme_dir() / "theme.json"


def _repo_root() -> Path:
    """Where fluxhound.ico lives: bundled as a PyInstaller data file (extracted
    to sys._MEIPASS) when frozen, since - unlike fluxhound_logo.png - it's an
    internal branding resource, not something a user would want to swap out
    next to the portable exe."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent.parent


ICON_PATH = _repo_root() / "fluxhound.ico"


def apply_icon(window: ctk.CTk | ctk.CTkToplevel) -> None:
    """Best-effort: sets a window's title-bar/taskbar icon to the FluxHound
    mark. Never raises if the .ico is missing (e.g. a source checkout that
    hasn't generated one) - branding is decoration, not required to run."""
    try:
        window.iconbitmap(str(ICON_PATH))
    except Exception:
        pass


def apply() -> None:
    """Load the FluxHound colour theme and fix the appearance mode to dark -
    call once, before constructing any CTk widget (including the root
    MainWindow). Dark has been this app's de facto look throughout; making it
    explicit avoids following the OS light/dark setting into an unstyled
    light-mode fallback that was never designed against."""
    ctk.set_default_color_theme(str(THEME_PATH))
    ctk.set_appearance_mode("dark")


def font_title() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=24, weight="bold")


def font_heading() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold")


def font_subheading() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold")


def font_body() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=13, weight="normal")


def font_small() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=11, weight="normal")


def font_badge() -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold")
