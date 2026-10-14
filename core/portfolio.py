"""Builds the full portfolio view (holdings, realised gains, FDs, XIRR) from the database.

Holdings keep amounts in their own currency (e.g. crypto in USD) and also carry *_inr
columns; anything aggregated across asset classes uses the INR columns.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import select, text

from core import fd as fdm
from core.db import get_engine, session_scope
from core.holdings import build_position
from core.models import Account, FixedDeposit, Instrument, Member, Txn
from core.returns import txn_cashflows, xirr
from core.tax import is_long_term


@dataclass
class Portfolio:
    as_of: date
    members: pd.DataFrame
    holdings: pd.DataFrame
    realised: pd.DataFrame
    fds: pd.DataFrame
    flows: dict = field(default_factory=dict)  # (member_id, asset_class) -> [(date, INR amount)]
    flows_native: dict = field(default_factory=dict)  # same, in the asset's own currency
    usd_inr: float | None = None

    def xirr_for(self, member_ids=None, asset_classes=None, native: bool = False) -> float | None:
        out = []
        for (mid, ac), f in (self.flows_native if native else self.flows).items():
            if (member_ids is None or mid in member_ids) and (asset_classes is None or ac in asset_classes):
                out.extend(f)
        return xirr(out)

    def summary(self) -> pd.DataFrame:
        """Invested and value in INR per member and asset class (open positions only)."""
        parts = []
        if not self.holdings.empty:
            h = self.holdings.groupby(["member_id", "member", "asset_class"])[["invested_inr", "value_inr"]].sum().reset_index()
            parts.append(h.rename(columns={"invested_inr": "invested", "value_inr": "value"}))
        if not self.fds.empty:
            f = self.fds
            started = f["start_date"] <= self.as_of
            live = f[started & ((f["status"] == "active") | (f["maturity_date"] >= self.as_of))]
            if not live.empty:
                f = live.groupby(["member_id", "member"])[["principal", "value"]].sum().reset_index()
                parts.append(f.rename(columns={"principal": "invested"}).assign(asset_class="fd"))
        if not parts:
            return pd.DataFrame(columns=["member_id", "member", "asset_class", "invested", "value"])
        return pd.concat(parts, ignore_index=True)


def latest_prices(as_of: date) -> pd.DataFrame:
    """Latest and previous price per instrument on or before as_of."""
    q = text(
        """
        SELECT instrument_id, date, price FROM (
            SELECT instrument_id, date, price,
                   ROW_NUMBER() OVER (PARTITION BY instrument_id ORDER BY date DESC) AS rn
            FROM price WHERE date <= :d
        ) WHERE rn <= 2
        """
    )
    with get_engine().connect() as c:
        df = pd.read_sql(q, c, params={"d": as_of.isoformat()})
    if df.empty:
        return pd.DataFrame(columns=["instrument_id", "price", "price_date", "prev_price"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values(["instrument_id", "date"], ascending=[True, False])
    first = df.groupby("instrument_id").nth(0).set_index("instrument_id")
    second = df.groupby("instrument_id").nth(1).set_index("instrument_id")
    out = first.rename(columns={"date": "price_date"})
    out["prev_price"] = second["price"]
    return out.reset_index()


def _fx_converter(rows):
    """Returns a function (amount, currency, date) -> INR."""
    foreign = [t.date for t, _, i, _ in rows if (i.currency or "INR") != "INR"]
    if not foreign:
        return lambda amount, cur, d: amount, None
    from prices import fx

    conv = fx.converter(min(foreign))
    if conv is None:
        raise RuntimeError("Couldn't get the USD/INR exchange rate. Check your internet connection and click 'Refresh prices now'.")
    return (lambda amount, cur, d: amount if cur == "INR" else amount * conv.rate(d)), conv


def load(member_ids: list[int] | None = None, as_of: date | None = None) -> Portfolio:
    as_of = as_of or date.today()
    with session_scope() as s:
        members = pd.DataFrame(
            [{"member_id": m.id, "member": m.name, "tax_slab": m.tax_slab, "residency": m.residency or "resident"}
             for m in s.scalars(select(Member).order_by(Member.id))]
        )
        q = (
            select(Txn, Account, Instrument, Member)
            .join(Account, Txn.account_id == Account.id)
            .join(Instrument, Txn.instrument_id == Instrument.id)
            .join(Member, Account.member_id == Member.id)
            .where(Txn.date <= as_of)
        )
        if member_ids:
            q = q.where(Member.id.in_(member_ids))
        rows = s.execute(q).all()
        fd_q = select(FixedDeposit, Member).join(Member, FixedDeposit.member_id == Member.id)
        if member_ids:
            fd_q = fd_q.where(Member.id.in_(member_ids))
        fd_rows = s.execute(fd_q).all()

    prices = latest_prices(as_of).set_index("instrument_id") if rows else pd.DataFrame()
    to_inr, conv = _fx_converter(rows)

    groups = defaultdict(list)
    meta = {}
    for t, a, i, m in rows:
        groups[(a.id, i.id)].append(t)
        meta[(a.id, i.id)] = (a, i, m)

    hold_rows, real_rows = [], []
    flows, flows_native = defaultdict(list), defaultdict(list)
    for key, txns in groups.items():
        a, i, m = meta[key]
        cur = i.currency or "INR"
        pos = build_position(txns)
        units = pos.units
        price = prev = None
        price_date = None
        if i.id in prices.index:
            price = float(prices.at[i.id, "price"])
            price_date = prices.at[i.id, "price_date"]
            pp = prices.at[i.id, "prev_price"]
            prev = float(pp) if pd.notna(pp) else None
        value = units * price if price is not None else pos.invested
        native_flows = txn_cashflows(txns, value if units > 1e-9 else 0.0, as_of)
        flows_native[(m.id, i.asset_class)].extend(native_flows)
        flows[(m.id, i.asset_class)].extend((d, to_inr(amt, cur, d)) for d, amt in native_flows)

        for r in pos.realised:
            cost_inr, proceeds_inr = to_inr(r.cost, cur, r.buy_date), to_inr(r.proceeds, cur, r.sell_date)
            real_rows.append(
                {
                    "member_id": m.id, "member": m.name, "asset_class": i.asset_class, "category": i.category,
                    "currency": cur, "instrument_id": i.id, "name": i.name, "symbol": i.symbol,
                    "buy_date": r.buy_date, "sell_date": r.sell_date, "units": r.units, "cost": r.cost,
                    "proceeds": r.proceeds, "gain": r.gain, "cost_inr": cost_inr, "proceeds_inr": proceeds_inr,
                    "gain_inr": proceeds_inr - cost_inr, "holding_days": r.holding_days, "missing_cost": r.missing_cost,
                }
            )
        if units <= 1e-6:
            continue
        lt_lots = [l for l in pos.lots if is_long_term(l.date, as_of, 12)]
        lt_units = sum(l.units for l in lt_lots)
        lt_cost = sum(l.units * l.cost_per_unit for l in lt_lots)
        invested_inr = sum(to_inr(l.units * l.cost_per_unit, cur, l.date) for l in pos.lots)
        value_inr = to_inr(value, cur, as_of)
        day_change = units * (price - prev) if price is not None and prev is not None else 0.0
        hold_rows.append(
            {
                "member_id": m.id, "member": m.name, "account_id": a.id, "account": a.label,
                "asset_class": i.asset_class, "instrument_id": i.id, "name": i.name, "symbol": i.symbol,
                "isin": i.isin, "category": i.category, "sector": i.sector, "currency": cur, "units": units,
                "avg_cost": pos.invested / units, "invested": pos.invested, "price": price,
                "price_date": price_date, "price_missing": price is None, "value": value,
                "pnl": value - pos.invested, "pnl_pct": (value / pos.invested - 1) if pos.invested else None,
                "day_change": day_change, "dividends": pos.dividends,
                "invested_inr": invested_inr, "value_inr": value_inr, "pnl_inr": value_inr - invested_inr,
                "day_change_inr": to_inr(day_change, cur, as_of),
                "xirr": xirr(txn_cashflows(txns, value, as_of)),
                "first_buy": min(l.date for l in pos.lots),
                "lt_unrealised_gain": (lt_units * price - lt_cost) if price is not None else 0.0,
                "sip_active": any(
                    t.type == "BUY" and t.note and "SIP" in t.note.upper() and (as_of - t.date).days <= 45 for t in txns
                ),
            }
        )

    fd_list = []
    for f, m in fd_rows:
        value = fdm.value_on(f, as_of) if f.start_date <= as_of else f.principal
        matured = f.maturity_date < as_of
        fy0, fy1 = fdm.fy_bounds(fdm.current_fy_start_year(as_of))
        if f.status == "active":
            flows[(m.id, "fd")].extend(fdm.cashflows(f, as_of))
            flows_native[(m.id, "fd")].extend(fdm.cashflows(f, as_of))
        fd_list.append(
            {
                "id": f.id, "member_id": m.id, "member": m.name, "bank": f.bank, "fd_number": f.fd_number,
                "fd_type": f.fd_type or "regular", "principal": f.principal, "rate": f.rate,
                "start_date": f.start_date, "maturity_date": f.maturity_date,
                "compounding": f.compounding, "payout": f.payout, "auto_renew": f.auto_renew, "status": f.status,
                "tds_deducted": f.tds_deducted, "notes": f.notes, "value": value,
                "maturity_amount": fdm.maturity_amount(f), "days_to_maturity": (f.maturity_date - as_of).days,
                "matured": matured, "interest_this_fy": fdm.interest_between(f, fy0, fy1),
                "interest_paid_out": sum(a for _, a in fdm.payouts(f, as_of)),
            }
        )

    return Portfolio(
        as_of=as_of,
        members=members if not members.empty else pd.DataFrame(columns=["member_id", "member", "tax_slab", "residency"]),
        holdings=pd.DataFrame(hold_rows),
        realised=pd.DataFrame(real_rows),
        fds=pd.DataFrame(fd_list),
        flows=dict(flows),
        flows_native=dict(flows_native),
        usd_inr=conv.rate(as_of) if conv else None,
    )
