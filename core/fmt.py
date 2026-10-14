def inr(x: float | None, decimals: int = 0) -> str:
    """Indian digit grouping: 12,34,567."""
    if x is None or x != x:
        return "-"
    neg = x < 0
    s = f"{abs(x):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}₹{whole}{'.' + frac if frac else ''}"


def inr_short(x: float | None) -> str:
    if x is None or x != x:
        return "-"
    a = abs(x)
    sign = "-" if x < 0 else ""
    if a >= 1e7:
        return f"{sign}₹{a / 1e7:.2f} Cr"
    if a >= 1e5:
        return f"{sign}₹{a / 1e5:.2f} L"
    return inr(x)


def usd(x: float | None, decimals: int = 0) -> str:
    if x is None or x != x:
        return "-"
    return f"{'-' if x < 0 else ''}${abs(x):,.{decimals}f}"


def money(x: float | None, currency: str = "INR", short: bool = False) -> str:
    if currency == "USD":
        return usd(x, 2 if x is not None and abs(x) < 100 else 0)
    return inr_short(x) if short else inr(x)


def pct(x: float | None, decimals: int = 1, signed: bool = True) -> str:
    if x is None or x != x:
        return "-"
    return f"{x * 100:+.{decimals}f}%" if signed else f"{x * 100:.{decimals}f}%"
