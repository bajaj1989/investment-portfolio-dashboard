"""USD/INR exchange rates, stored in the price table under a pseudo-instrument."""
import bisect
import logging
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import select

from core.db import session_scope
from core.models import Instrument, Price
from prices.store import save_prices

log = logging.getLogger(__name__)
FX_KEY = "USDINR"


def instrument_id() -> int:
    with session_scope() as s:
        inst = s.scalar(select(Instrument).where(Instrument.asset_class == "fx", Instrument.key == FX_KEY))
        if inst is None:
            inst = Instrument(asset_class="fx", key=FX_KEY, name="USD/INR", symbol="INR=X", category="fx", currency="INR")
            s.add(inst)
            s.flush()
        return inst.id


def update(since: date | None = None) -> int:
    start = since or (date.today() - timedelta(days=10))
    df = yf.download("INR=X", start=start.isoformat(), progress=False, auto_adjust=False)
    if df.empty:
        return 0
    close = df["Close"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    iid = instrument_id()
    return save_prices([(iid, d.date(), float(v)) for d, v in close.dropna().items()])


class Converter:
    def __init__(self, rates: dict[date, float]):
        self.days = sorted(rates)
        self.rates = rates

    def rate(self, d: date) -> float:
        i = bisect.bisect_right(self.days, d) - 1
        return self.rates[self.days[max(i, 0)]]


def _stored() -> dict[date, float]:
    iid = instrument_id()
    with session_scope() as s:
        return {p.date: p.price for p in s.scalars(select(Price).where(Price.instrument_id == iid))}


def converter(needed_from: date | None = None) -> Converter | None:
    """USD->INR converter covering `needed_from` onwards; fetches missing rates if needed."""
    rates = _stored()
    stale = not rates or max(rates) < date.today() - timedelta(days=4)
    too_late = needed_from is not None and (not rates or min(rates) > needed_from + timedelta(days=5))
    if stale or too_late:
        try:
            start = min(needed_from or date.today(), max(rates) if rates and not too_late else date.today()) - timedelta(days=7)
            update(start)
            rates = _stored()
        except Exception as e:  # network problems: fall back to whatever is stored
            log.warning("USD/INR update failed: %s", e)
    return Converter(rates) if rates else None
