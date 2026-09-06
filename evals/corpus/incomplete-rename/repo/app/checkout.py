"""The checkout path."""

from app.utils import format_price


def checkout(total: float) -> str:
    """Render the total a customer is charged."""
    return format_price(total)
