"""Indian stock prices from Yahoo Finance (NSE .NS, falling back to BSE .BO)."""
import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy import select

from core.db import session_scope
from core.models import Instrument
from prices.store import save_prices

log = logging.getLogger(__name__)


def _stocks() -> list[tuple[int, str]]:
    with session_scope() as s:
        return [(i.id, i.symbol) for i in s.scalars(select(Instrument).where(Instrument.asset_class == "stock")) if i.symbol]


def _download(tickers: list[str], start: date) -> pd.DataFrame:
    if not tickers:
        return pd.DataFrame()
    df = yf.download(tickers, start=start.isoformat(), progress=False, auto_adjust=False, group_by="ticker", threads=True)
    return df


def _closes(df: pd.DataFrame, ticker: str) -> pd.Series:
    try:
        if isinstance(df.columns, pd.MultiIndex):
            s = df[ticker]["Close"]
        else:
            s = df["Close"]
        return s.dropna()
    except KeyError:
        return pd.Series(dtype=float)


def update(since: date | None = None) -> int:
    """Fetch daily closes since a date (default: last 7 days)."""
    stocks = _stocks()
    if not stocks:
        return 0
    start = since or (date.today() - timedelta(days=7))
    rows, missing = [], []
    df = _download([f"{sym}.NS" for _, sym in stocks], start)
    for inst_id, sym in stocks:
        closes = _closes(df, f"{sym}.NS")
        if closes.empty:
            missing.append((inst_id, sym))
        rows += [(inst_id, d.date(), float(v)) for d, v in closes.items()]
    if missing:
        df = _download([f"{sym}.BO" for _, sym in missing], start)
        for inst_id, sym in missing:
            closes = _closes(df, f"{sym}.BO")
            if closes.empty:
                log.warning("No price found for %s", sym)
            rows += [(inst_id, d.date(), float(v)) for d, v in closes.items()]
    return save_prices(rows)


def fill_sectors(limit: int = 25) -> int:
    """Look up sector for stocks that don't have one yet (slow, so capped per run)."""
    with session_scope() as s:
        todo = list(s.scalars(select(Instrument).where(Instrument.asset_class == "stock", Instrument.sector.is_(None)).limit(limit)))
        for inst in todo:
            try:
                info = yf.Ticker(f"{inst.symbol}.NS").info or {}
                inst.sector = info.get("sector") or "Other"
            except Exception as e:  # yfinance raises many types on bad tickers
                log.warning("Sector lookup failed for %s: %s", inst.symbol, e)
                inst.sector = "Other"
        return len(todo)
