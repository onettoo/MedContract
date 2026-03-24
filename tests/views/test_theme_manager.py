import pytest
from views.theme_manager import ThemeManager

def test_theme_manager_initialization():
    """ThemeManager initializes with light mode by default"""
    manager = ThemeManager()
    assert manager.current_theme == "light"

def test_theme_manager_toggle():
    """Can toggle between light and dark modes"""
    manager = ThemeManager()
    assert manager.current_theme == "light"

    manager.toggle_theme()
    assert manager.current_theme == "dark"

    manager.toggle_theme()
    assert manager.current_theme == "light"

def test_theme_manager_set_theme():
    """Can set theme explicitly"""
    manager = ThemeManager()
    manager.set_theme("dark")
    assert manager.current_theme == "dark"

    manager.set_theme("light")
    assert manager.current_theme == "light"

def test_theme_manager_signal_emitted():
    """Emits signal when theme changes"""
    manager = ThemeManager()
    signals_received = []

    manager.theme_changed.connect(lambda theme: signals_received.append(theme))

    manager.set_theme("dark")
    assert "dark" in signals_received
