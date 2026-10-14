from datetime import date

from pyxirr import InvalidPaymentsError, xirr as _xirr


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annualised return for (date, amount) cashflows; investments negative. None if undefined."""
    flows = [(d, a) for d, a in flows if a and abs(a) > 1e-9]
    if len(flows) < 2:
        return None
    if not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    if min(d for d, _ in flows) == max(d for d, _ in flows):
        return None
    try:
        r = _xirr([d for d, _ in flows], [a for _, a in flows])
    except (InvalidPaymentsError, ValueError, OverflowError):
        return None
    if r is None or r != r or abs(r) > 100:
        return None
    return float(r)


def txn_cashflows(txns, terminal_value: float = 0.0, on: date | None = None) -> list[tuple[date, float]]:
    flows = []
    for t in txns:
        if t.type == "BUY":
            flows.append((t.date, -(t.amount + (t.fees or 0))))
        elif t.type in ("SELL", "TRANSFER_OUT"):
            flows.append((t.date, t.amount - (t.fees or 0)))
        elif t.type == "DIVIDEND":
            flows.append((t.date, t.amount))
        elif t.type == "FEE":
            flows.append((t.date, -t.amount))
    if terminal_value:
        flows.append((on or date.today(), terminal_value))
    return flows
