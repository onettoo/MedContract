from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class UiPalette:
    accent: str = "#1a6b7c"
    accent_hover: str = "#155e6d"
    ink: str = "#0c0f12"
    ink_2: str = "#4a5260"
    ink_3: str = "#9199a6"
    line: str = "#e8eaed"
    white: str = "#ffffff"
    bg: str = "#f9fafb"
    good: str = "#16a34a"
    good_bg: str = "rgba(22,163,74,0.08)"
    good_border: str = "rgba(22,163,74,0.22)"
    warn: str = "#92400e"
    warn_bg: str = "rgba(217,119,6,0.10)"
    warn_border: str = "rgba(217,119,6,0.22)"
    danger: str = "#c0392b"
    danger_bg: str = "rgba(192,57,43,0.08)"
    danger_border: str = "rgba(192,57,43,0.22)"


PALETTE = UiPalette()


@dataclass(frozen=True)
class ClinicPalette:
    """MedContract Clinic - Professional Healthcare Palette"""
    # Primary colors
    primary: str = "#2b6c7e"      # Clinic primary (trust, identity)
    primary_hover: str = "#3d8fa3" # Hover state
    primary_active: str = "#1f4d5f" # Active/pressed state

    # Status colors
    success: str = "#059669"        # Positive metrics
    warning: str = "#d97706"        # Caution/attention
    danger: str = "#dc2626"         # Critical/urgent

    # Light mode neutrals (modo unico)
    light_bg: str = "#ffffff"
    light_surface: str = "#f8fafc"
    light_text_primary: str = "#0f172a"
    light_text_secondary: str = "#64748b"
    light_border: str = "#e2e8f0"


# Create singleton instance
CLINIC_PALETTE = ClinicPalette()


@lru_cache(maxsize=1)
def get_sans_family() -> str:
    """
    Carrega DM Sans de assets/fonts/ e retorna o nome da família.
    Resultado cacheado — I/O de disco ocorre apenas uma vez por sessão.
    """
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase

    fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    family = "Segoe UI"
    if fonts_dir.exists():
        for ttf in sorted(fonts_dir.glob("*.ttf")):
            fid = QFontDatabase.addApplicationFont(str(ttf))
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams and "DM Sans" in fams[0]:
                    family = fams[0]
    return family
