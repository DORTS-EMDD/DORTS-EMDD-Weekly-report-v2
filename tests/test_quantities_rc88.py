"""RC-88 (external review): prefix currencies of ranges and unitless quantities (RC-29)."""

from __future__ import annotations

import pytest

from src.weekly_report.quantities import checked_quantities, is_grounded, stated_quantities


@pytest.mark.parametrize(
    ("text", "codes"),
    [("€10-20 million", {"EUR"}), ("$5-10 billion", {"USD"}), ("€10 million to 20 million", {"EUR"})],
)
def test_a_prefix_currency_applies_to_the_upper_bound(text, codes):
    lower, upper = stated_quantities(text)
    assert lower.unit == upper.unit and codes <= upper.unit


def test_the_upper_bound_is_grounded_only_by_its_currency():
    evidence = stated_quantities("The contract is worth €10-20 million.")
    assert is_grounded(checked_quantities("2,000萬歐元")[0], evidence)
    assert not is_grounded(checked_quantities("2,000萬美元")[0], evidence)


@pytest.mark.parametrize("source", ["€50,000", "50,000 km", "50,000 m²", "50,000%"])
def test_a_unitless_number_is_not_grounded_by_a_number_with_a_unit(source):
    written = checked_quantities("每日5萬人次")[0]
    assert not written.unit
    assert not is_grounded(written, stated_quantities(source))


def test_a_unitless_number_is_grounded_by_a_unitless_number():
    written = checked_quantities("每日5萬人次")[0]
    assert is_grounded(written, stated_quantities("about 50,000 passengers a day"))
