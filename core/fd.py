"""Fixed deposit interest maths.

Cumulative FDs compound for whole periods; the incomplete period accrues simple
interest, which is how most Indian banks quote maturity values.
Payout FDs pay simple interest at each payout date and keep principal constant.
"""
import calendar
from datetime import date, timedelta

PERIODS_PER_YEAR = {"monthly": 12, "quarterly": 4, "half_yearly": 2, "yearly": 1, "simple": 0}


def add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _boundaries(start: date, end: date, per_year: int) -> list[date]:
    """Period end dates strictly after start and <= end."""
    if per_year <= 0:
        return []
    step = 12 // per_year
    out, k = [], 1
    while True:
        b = add_months(start, step * k)
        if b > end:
            return out
        out.append(b)
        k += 1


def value_on(fd, on: date) -> float:
    """Value held in the FD on a date (principal plus unpaid interest)."""
    d = min(max(on, fd.start_date), fd.maturity_date)
    r = fd.rate / 100.0
    p = fd.principal

    if fd.payout != "cumulative":
        bounds = _boundaries(fd.start_date, d, PERIODS_PER_YEAR.get(fd.payout, 4))
        last = bounds[-1] if bounds else fd.start_date
        return p + p * r * (d - last).days / 365.0

    n = PERIODS_PER_YEAR.get(fd.compounding, 4)
    if n == 0:
        return p * (1 + r * (d - fd.start_date).days / 365.0)
    bounds = _boundaries(fd.start_date, d, n)
    k = len(bounds)
    last = bounds[-1] if bounds else fd.start_date
    compounded = p * (1 + r / n) ** k
    return compounded * (1 + r * (d - last).days / 365.0)


def payouts(fd, upto: date | None = None) -> list[tuple[date, float]]:
    """Interest payouts for non-cumulative FDs (date, amount)."""
    if fd.payout == "cumulative":
        return []
    end = min(upto or fd.maturity_date, fd.maturity_date)
    per_year = PERIODS_PER_YEAR.get(fd.payout, 4)
    r = fd.rate / 100.0
    return [(b, fd.principal * r / per_year) for b in _boundaries(fd.start_date, end, per_year)]


def maturity_amount(fd) -> float:
    """Amount received at maturity (for payout FDs: principal + final partial interest)."""
    return value_on(fd, fd.maturity_date)


def total_interest_until(fd, on: date) -> float:
    """Interest earned (accrual basis) from start until a date."""
    if on <= fd.start_date:
        return 0.0
    paid = sum(a for _, a in payouts(fd, on))
    return value_on(fd, on) + paid - fd.principal


def interest_between(fd, start: date, end: date) -> float:
    """Interest accrued in [start, end], e.g. a financial year (for tax/15G/15H)."""
    return total_interest_until(fd, end) - total_interest_until(fd, start - timedelta(days=1))


def cashflows(fd, today: date) -> list[tuple[date, float]]:
    """Investor cashflows for XIRR: -principal, +payouts, +current value."""
    flows = [(fd.start_date, -fd.principal)]
    flows += [(d, a) for d, a in payouts(fd, today) if d <= today]
    flows.append((today if today < fd.maturity_date else fd.maturity_date, value_on(fd, today)))
    return flows


def fy_bounds(fy_start_year: int) -> tuple[date, date]:
    return date(fy_start_year, 4, 1), date(fy_start_year + 1, 3, 31)


def current_fy_start_year(today: date | None = None) -> int:
    t = today or date.today()
    return t.year if t.month >= 4 else t.year - 1
