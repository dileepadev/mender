from decimal import Decimal

from pkg.totals import total


def test_total_sums_prices():
    assert total(["1.50", "2.50"]) == Decimal("4.00")
