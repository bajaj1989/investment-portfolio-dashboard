"""Daily net-worth snapshots (per member and asset class) for the history chart."""
import logging
from datetime import date, timedelta

from sqlalchemy import delete, func, select

from core import portfolio
from core.db import session_scope
from core.models import FixedDeposit, Snapshot, Txn

log = logging.getLogger(__name__)


def take(as_of: date | None = None, p: portfolio.Portfolio | None = None) -> int:
    as_of = as_of or date.today()
    p = p or portfolio.load(as_of=as_of)
    summary = p.summary()
    with session_scope() as s:
        s.execute(delete(Snapshot).where(Snapshot.date == as_of))
        for r in summary.groupby(["member_id", "asset_class"])[["invested", "value"]].sum().reset_index().itertuples():
            s.add(Snapshot(date=as_of, member_id=int(r.member_id), asset_class=r.asset_class, invested=float(r.invested), value=float(r.value)))
    return len(summary)


def has_today() -> bool:
    with session_scope() as s:
        return s.scalar(select(func.count()).select_from(Snapshot).where(Snapshot.date == date.today())) > 0


def first_activity() -> date | None:
    with session_scope() as s:
        dates = [s.scalar(select(func.min(Txn.date))), s.scalar(select(func.min(FixedDeposit.start_date)))]
    dates = [d for d in dates if d]
    return min(dates) if dates else None


def history_dates(start: date, end: date) -> list[date]:
    """Month-ends before the last year, weekly within it, always including end."""
    out = []
    weekly_from = end - timedelta(days=365)
    d = date(start.year, start.month, 1)
    while d < weekly_from:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        out.append(nxt - timedelta(days=1))
        d = nxt
    d = max(weekly_from, start)
    while d < end:
        out.append(d)
        d += timedelta(days=7)
    out.append(end)
    return sorted({x for x in out if start <= x <= end})


def rebuild_history(progress=None) -> int:
    """Fetches historical prices, then recomputes snapshots back to the first investment."""
    from prices import amfi, coingecko, fx, nse

    start = first_activity()
    if not start:
        return 0
    steps = [
        ("USD/INR rate history", lambda: fx.update(since=start)),
        ("Mutual fund NAV history", lambda: amfi.backfill_history(start)),
        ("Stock price history", lambda: nse.update(since=start)),
        ("Crypto price history (last 365 days)", lambda: coingecko.backfill_history(365)),
    ]
    for i, (label, fn) in enumerate(steps):
        if progress:
            progress(i / (len(steps) + 1), label)
        try:
            fn()
        except Exception as e:  # network failures shouldn't block the rest
            log.warning("%s failed: %s", label, e)
    dates = history_dates(start, date.today())
    for n, d in enumerate(dates):
        if progress and n % 5 == 0:
            progress((len(steps) + n / len(dates)) / (len(steps) + 1), f"Snapshot {d}")
        take(d)
    if progress:
        progress(1.0, "Done")
    return len(dates)
