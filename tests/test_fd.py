from datetime import date
from types import SimpleNamespace

import pytest

from core import fd


def make(**kw):
    base = dict(principal=100000.0, rate=7.0, start_date=date(2025, 1, 1), maturity_date=date(2026, 1, 1),
                compounding="quarterly", payout="cumulative")
    base.update(kw)
    return SimpleNamespace(**base)


def test_cumulative_quarterly_maturity():
    assert fd.maturity_amount(make()) == pytest.approx(100000 * 1.0175**4, rel=1e-9)


def test_value_before_start_is_principal_and_grows():
    f = make()
    assert fd.value_on(f, date(2024, 6, 1)) == 100000
    assert 100000 < fd.value_on(f, date(2025, 6, 1)) < fd.maturity_amount(f)


def test_simple_interest():
    f = make(compounding="simple", maturity_date=date(2025, 7, 2))
    assert fd.maturity_amount(f) == pytest.approx(100000 * (1 + 0.07 * 182 / 365))


def test_quarterly_payout():
    f = make(payout="quarterly")
    pays = fd.payouts(f)
    assert len(pays) == 4
    assert sum(a for _, a in pays) == pytest.approx(7000)
    assert fd.maturity_amount(f) == pytest.approx(100000)


def test_interest_split_across_financial_years_adds_up():
    f = make()
    a = fd.interest_between(f, *fd.fy_bounds(2024))
    b = fd.interest_between(f, *fd.fy_bounds(2025))
    assert a + b == pytest.approx(fd.maturity_amount(f) - 100000, rel=1e-9)
    assert a > 0 and b > 0


def test_add_months_clamps_day():
    assert fd.add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
