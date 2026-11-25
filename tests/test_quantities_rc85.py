"""RC-85 (section A.66): a currency-signed number's magnitude letter in either case, and a hyphenated magnitude word.

Run 45103217994 failed Forte-Citnalta (MTA Chambers Street J/Z) at
factual_summary_quantity_ungrounded: the Validator read "$118.95M" as 118.95
metres, so no correct rendering of the amount could be grounded.
"""

from __future__ import annotations

import pytest

from src.weekly_report.quantities import checked_quantities, is_grounded, stated_quantities


@pytest.mark.parametrize(
    "text, value",
    [("a $118.95M contract", 118_950_000), ("a $118.95m contract", 118_950_000), ("a $2B plan", 2_000_000_000),
     ("a €5K fee", 5_000), ("a $118.95-million contract", 118_950_000), ("a €1.2-billion order", 1_200_000_000)],
)
def test_currency_signed_magnitudes(text, value):
    (quantity,) = stated_quantities(text)
    assert quantity.values == frozenset({float(value)})
    assert "length" not in quantity.unit


def test_without_a_currency_sign_an_uppercase_m_is_unchanged():
    (quantity,) = stated_quantities("a 118.95 M section")
    assert quantity.unit == frozenset({"length"})


def test_the_forte_citnalta_amount_is_grounded_but_the_currency_rule_stays():
    evidence = stated_quantities("Forte-Citnalta won a $118.95M contract for the station.")
    grounded = {q.text: is_grounded(q, evidence) for q in checked_quantities("MTA 以 $1.1895 億決標，合約 $118.95 百萬")}
    assert grounded == {"1.1895 億": True, "118.95 百萬": True}
    # RC-29 unchanged: "$" is shared by several currencies, so 美元 is more specific than the source.
    (quantity,) = checked_quantities("MTA 以 1.1895 億美元決標")
    assert not is_grounded(quantity, evidence)
