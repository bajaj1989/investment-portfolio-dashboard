"""Zerodha Kite Connect: daily login, holdings reconciliation and live prices.

Kite only exposes average buy price (not individual trades), so the tradebook CSV stays
the source of truth; Kite is used to check holdings match and to refresh prices.
"""
from datetime import date

import pandas as pd
from kiteconnect import KiteConnect
from sqlalchemy import select

from core.db import session_scope
from core.models import Instrument
from core.vault import get_secret, set_secret
from importers.base import ParsedImport, Record, make_ref
from prices.store import save_prices


def creds(member_id: int) -> tuple[str | None, str | None]:
    return get_secret(f"kite_api_key:{member_id}"), get_secret(f"kite_api_secret:{member_id}")


def save_creds(member_id: int, api_key: str, api_secret: str):
    set_secret(f"kite_api_key:{member_id}", api_key.strip())
    set_secret(f"kite_api_secret:{member_id}", api_secret.strip())


def login_url(member_id: int) -> str:
    key, _ = creds(member_id)
    return KiteConnect(api_key=key).login_url()


def complete_login(member_id: int, request_token_or_url: str):
    """Accepts the request_token or the whole redirect URL pasted by the user."""
    token = request_token_or_url.strip()
    if "request_token=" in token:
        token = token.split("request_token=")[1].split("&")[0]
    key, secret = creds(member_id)
    kite = KiteConnect(api_key=key)
    session = kite.generate_session(token, api_secret=secret)
    set_secret(f"kite_access_token:{member_id}", f"{date.today().isoformat()}|{session['access_token']}")


def client(member_id: int) -> KiteConnect | None:
    """Returns a logged-in client, or None if today's login hasn't happened (tokens expire daily)."""
    key, _ = creds(member_id)
    stored = get_secret(f"kite_access_token:{member_id}")
    if not key or not stored or "|" not in stored:
        return None
    d, token = stored.split("|", 1)
    if d != date.today().isoformat():
        return None
    kite = KiteConnect(api_key=key)
    kite.set_access_token(token)
    return kite


def holdings(member_id: int) -> pd.DataFrame:
    kite = client(member_id)
    if kite is None:
        raise RuntimeError("Please log in to Kite first (login is needed once a day).")
    rows = kite.holdings()
    return pd.DataFrame(
        [
            {
                "isin": h["isin"], "symbol": h["tradingsymbol"],
                "kite_units": float(h["quantity"]) + float(h.get("t1_quantity", 0) or 0),
                "avg_price": float(h["average_price"]), "last_price": float(h["last_price"]),
            }
            for h in rows
        ]
    )


def save_live_prices(kite_holdings: pd.DataFrame) -> int:
    with session_scope() as s:
        by_isin = {i.isin: i.id for i in s.scalars(select(Instrument).where(Instrument.asset_class == "stock")) if i.isin}
    rows = [(by_isin[r.isin], date.today(), r.last_price) for r in kite_holdings.itertuples() if r.isin in by_isin]
    return save_prices(rows)


def opening_balance(kite_holdings: pd.DataFrame, member_id: int, as_of: date, isins: list[str]) -> ParsedImport:
    """Creates BUY records at Kite's average price for stocks with no tradebook history."""
    out = ParsedImport("kite_opening", member_id, "Kite holdings", make_ref("kite", member_id, as_of, sorted(isins)))
    for r in kite_holdings[kite_holdings["isin"].isin(isins)].itertuples():
        out.records.append(
            Record(
                account_type="zerodha", account_id_ext="ZERODHA", account_label="Zerodha", asset_class="stock",
                inst_key=r.isin, inst_name=r.symbol, symbol=r.symbol, isin=r.isin, date=as_of, type="BUY",
                units=r.kite_units, price=r.avg_price, amount=r.kite_units * r.avg_price,
                note="Opening balance from Kite (average price)",
                ext_ref="ko:" + make_ref(member_id, r.isin, as_of, r.kite_units, r.avg_price),
            )
        )
    return out
