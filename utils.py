"""
Utility functions for MedContract application.
"""

def br_money(value: float) -> str:
    """
    Format a float value as Brazilian currency (R$).

    Args:
        value: The monetary value to format.

    Returns:
        Formatted string in Brazilian Real format.
    """
    try:
        s = f"{float(value):,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s}"
    except (ValueError, TypeError):
        return "R$ 0,00"