from app.checkout import checkout


def test_checkout_formats_the_total():
    assert checkout(100) == "$100.00"
