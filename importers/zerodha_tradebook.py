"""Zerodha Console > Reports > Tradebook (Equity) CSV.

Expected columns: symbol, isin, trade_date, exchange, segment, series, trade_type,
quantity, price, trade_id, order_id, order_execution_time.
"""
import io

import pandas as pd

from importers.base import ParsedImport, Record, file_hash, make_ref

REQUIRED = {"symbol", "isin", "trade_date", "trade_type", "quantity", "price", "trade_id"}


def parse(data: bytes, file_name: str, member_id: int, client_id: str = "") -> ParsedImport:
    df = pd.read_csv(io.BytesIO(data), dtype=str)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"This doesn't look like a Zerodha tradebook CSV (missing columns: {', '.join(sorted(missing))}).")

    out = ParsedImport("zerodha_tradebook", member_id, file_name, file_hash(data))
    acc_ext = client_id.strip().upper() or "ZERODHA"
    label = f"Zerodha {client_id.strip().upper()}".strip()
    if "segment" in df.columns:
        other = df[~df["segment"].fillna("EQ").str.upper().isin(["EQ"])]
        if len(other):
            out.warnings.append(f"Skipped {len(other)} non-equity (F&O/currency/commodity) trades.")
        df = df[df["segment"].fillna("EQ").str.upper().isin(["EQ"])]

    for row in df.itertuples(index=False):
        qty = float(row.quantity)
        price = float(row.price)
        side = str(row.trade_type).strip().lower()
        if side not in ("buy", "sell") or qty <= 0:
            continue
        isin = str(row.isin).strip()
        sym = str(row.symbol).strip().upper()
        d = pd.to_datetime(row.trade_date).date()
        out.records.append(
            Record(
                account_type="zerodha", account_id_ext=acc_ext, account_label=label, asset_class="stock",
                inst_key=isin or sym, inst_name=sym, symbol=sym, isin=isin or None, date=d,
                type="BUY" if side == "buy" else "SELL", units=qty, price=price, amount=qty * price,
                ext_ref="zt:" + make_ref(member_id, getattr(row, "exchange", ""), row.trade_id,
                                         getattr(row, "order_id", ""), d, side, qty, price),
            )
        )
    if not out.records:
        out.warnings.append("No equity trades found in this file.")
    return out
