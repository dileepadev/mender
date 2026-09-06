"""Totalling helpers."""

import os
from decimal import Decimal


def total(prices: list[str]) -> Decimal:
    """Sum a list of price strings."""
    return sum((Decimal(price) for price in prices), Decimal(0))
