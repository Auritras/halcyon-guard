import pytest

from halcyon.money import inr


@pytest.mark.parametrize("amount,text", [
    (4200, "₹4,200"), (120000, "₹1,20,000"), (25000, "₹25,000"), (999, "₹999"),
    (10000000, "₹1,00,00,000"), (4200.5, "₹4,200.50"), (0, "₹0"),
])
def test_inr(amount, text):
    assert inr(amount) == text
