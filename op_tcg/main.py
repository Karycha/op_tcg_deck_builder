"""Uruchomienie aplikacji (CustomTkinter)."""
from __future__ import annotations

import customtkinter as ctk

from op_tcg.ui.main_window import DeckBuilderApp


def run() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    app = DeckBuilderApp()
    app.mainloop()
