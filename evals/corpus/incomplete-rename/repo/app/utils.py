"""Formatting helpers."""


def format_currency(amount: float) -> str:
    """Render an amount as a price string."""
    return f"${amount:.2f}"
