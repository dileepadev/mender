def discount(total: float, rate: float) -> float:
    return total - total * rate


def test_discount_applies():
    assert discount(100, 0.1) == 90
