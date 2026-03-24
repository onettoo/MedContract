"""Theme manager for light/dark mode switching and persistence."""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QObject, Signal

class ThemeManager(QObject):
    """Manages application theme (light/dark) and persistence."""

    theme_changed = Signal(str)  # Emits theme name

    def __init__(self):
        super().__init__()
        self._current_theme = "light"
        self._config_path = Path.home() / ".medcontract" / "theme.conf"
        self._load_theme()

    @property
    def current_theme(self) -> str:
        """Get current theme name."""
        return self._current_theme

    def set_theme(self, theme: str) -> None:
        """Set theme and save preference."""
        if theme not in ("light", "dark"):
            raise ValueError(f"Invalid theme: {theme}")

        if self._current_theme != theme:
            self._current_theme = theme
            self._save_theme()
            self.theme_changed.emit(theme)

    def toggle_theme(self) -> None:
        """Toggle between light and dark modes."""
        next_theme = "dark" if self._current_theme == "light" else "light"
        self.set_theme(next_theme)

    def _load_theme(self) -> None:
        """Load saved theme preference."""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r") as f:
                    saved_theme = f.read().strip()
                    if saved_theme in ("light", "dark"):
                        self._current_theme = saved_theme
            except (IOError, ValueError):
                pass  # Use default (light)

    def _save_theme(self) -> None:
        """Save current theme preference."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._config_path, "w") as f:
                f.write(self._current_theme)
        except IOError:
            pass  # Silently fail if can't save
