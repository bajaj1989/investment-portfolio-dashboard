from datetime import date

from core.portfolio import Portfolio


def current_value(goal, p: Portfolio) -> float:
    classes = [c for c in goal.asset_classes.split(",") if c]
    s = p.summary()
    if goal.member_id:
        s = s[s["member_id"] == goal.member_id]
    return float(s[s["asset_class"].isin(classes)]["value"].sum())


def months_left(target: date, today: date | None = None) -> int:
    t = today or date.today()
    return max((target.year - t.year) * 12 + (target.month - t.month), 0)


def required_monthly(target: float, current: float, annual_return_pct: float, months: int) -> float:
    """Monthly investment needed so current corpus + SIP reaches target."""
    if months <= 0:
        return max(target - current, 0.0)
    r = annual_return_pct / 100 / 12
    future_current = current * (1 + r) ** months
    gap = target - future_current
    if gap <= 0:
        return 0.0
    if r == 0:
        return gap / months
    return gap * r / ((1 + r) ** months - 1)


def projection(current: float, monthly: float, annual_return_pct: float, months: int) -> list[float]:
    r = annual_return_pct / 100 / 12
    vals, v = [current], current
    for _ in range(months):
        v = v * (1 + r) + monthly
        vals.append(v)
    return vals
