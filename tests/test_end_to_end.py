from datetime import date, timedelta

import pytest

from core import portfolio, snapshot
from core.db import session_scope
from core.models import FixedDeposit
from importers import base, cryptocom_csv, zerodha_tradebook
from prices.store import save_prices

TRADEBOOK = b"""symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
INFY,INE009A01021,2023-01-10,NSE,EQ,EQ,buy,false,10.000000,1500.00,1001,2001,2023-01-10T10:00:00
INFY,INE009A01021,2024-02-10,NSE,EQ,EQ,sell,false,4.000000,1700.00,1002,2002,2024-02-10T10:00:00
NIFTY24JANFUT,,2024-01-10,NFO,FO,,buy,false,50,21000,1003,2003,2024-01-10T10:00:00
"""

CRYPTO = b"""Timestamp (UTC),Transaction Description,Currency,Amount,To Currency,To Amount,Native Currency,Native Amount,Native Amount (in USD),Transaction Kind,Transaction Hash
2024-01-05 10:00:00,Buy BTC,BTC,0.01,,,INR,30000,360,crypto_purchase,
2024-03-05 10:00:00,BTC -> ETH,BTC,-0.004,ETH,0.05,INR,16000,190,crypto_exchange,
2024-04-01 10:00:00,Card Cashback,CRO,10,,,INR,80,1,referral_card_cashback,
2024-05-01 10:00:00,Lock CRO,CRO,-10,,,INR,80,1,lockup_lock,
2024-06-01 10:00:00,Withdraw ETH,ETH,-0.01,,,INR,3000,36,crypto_withdrawal,
"""


def _instrument_id(asset_class, key):
    from sqlalchemy import select

    from core.models import Instrument

    with session_scope() as s:
        return s.scalar(select(Instrument.id).where(Instrument.asset_class == asset_class, Instrument.key == key))


def test_zerodha_import_and_valuation(fresh_db):
    parsed = zerodha_tradebook.parse(TRADEBOOK, "tb.csv", 1, "AB1234")
    assert len(parsed.records) == 2
    assert any("non-equity" in w for w in parsed.warnings)
    assert base.commit(parsed) == (2, 0)
    assert base.commit(zerodha_tradebook.parse(TRADEBOOK, "tb.csv", 1, "AB1234")) == (0, 2)

    iid = _instrument_id("stock", "INE009A01021")
    save_prices([(iid, date.today() - timedelta(days=1), 1800.0), (iid, date.today(), 1900.0)])
    p = portfolio.load()
    h = p.holdings.iloc[0]
    assert h["units"] == pytest.approx(6)
    assert h["invested"] == pytest.approx(9000)
    assert h["value"] == pytest.approx(11400)
    assert h["day_change"] == pytest.approx(600)
    assert p.realised.iloc[0]["gain"] == pytest.approx(800)
    assert p.xirr_for() is not None


def _usd_inr(rates):
    from prices import fx

    save_prices([(fx.instrument_id(), d, r) for d, r in rates])


def test_cryptocom_import_in_usd(fresh_db):
    _usd_inr([(date(2024, 1, 1), 83.0), (date(2024, 3, 1), 82.0), (date.today() - timedelta(days=1), 88.0)])
    parsed = cryptocom_csv.parse(CRYPTO, "c.csv", 2)
    assert all(r.currency == "USD" for r in parsed.records)
    base.commit(parsed)

    btc = _instrument_id("crypto", "BTC")
    save_prices([(btc, date.today() - timedelta(days=1), 100000.0)])
    p = portfolio.load()
    h = p.holdings.set_index("symbol")
    assert h.at["BTC", "units"] == pytest.approx(0.006)
    assert h.at["ETH", "units"] == pytest.approx(0.04)
    assert h.at["CRO", "units"] == pytest.approx(10)
    assert h.at["BTC", "currency"] == "USD"
    assert h.at["BTC", "invested"] == pytest.approx(216)  # 0.006 of the $360 purchase
    assert h.at["BTC", "value"] == pytest.approx(600)
    assert h.at["BTC", "invested_inr"] == pytest.approx(216 * 83.0)
    assert h.at["BTC", "value_inr"] == pytest.approx(600 * 88.0)
    assert p.usd_inr == pytest.approx(88.0)

    sale = p.realised.iloc[0]
    assert sale["cost"] == pytest.approx(144)
    assert sale["proceeds"] == pytest.approx(190)
    assert sale["gain_inr"] == pytest.approx(190 * 82.0 - 144 * 83.0)
    assert len(p.realised) == 1

    crypto_inr = p.summary().query("asset_class == 'crypto'")["value"].sum()
    assert crypto_inr == pytest.approx(h["value_inr"].sum())


LIMIT_ORDERS = b"""Timestamp (UTC),Transaction Description,Currency,Amount,To Currency,To Amount,Native Currency,Native Amount,Native Amount (in USD),Transaction Kind,Transaction Hash
2024-03-13 11:26:50,Sold SOL,SOL,-10.0,SGD,1995.40,USD,1484.25,1484.25,crypto_viban_exchange,
2024-03-13 11:26:19,SOL > USDT,SOL,10.0,USDT,1540.0,USD,1516.24,1516.24,trading.limit_order.crypto_wallet.fund_unlock,
2024-03-13 10:32:56,SOL > USDT,SOL,-10.0,USDT,1540.0,USD,1516.21,1516.21,trading.limit_order.crypto_wallet.fund_lock,
2024-03-13 05:50:08,Sell SOL,SOL,10.0,SGD,2050.00,USD,1525.44,1525.44,trading.limit_order.cash_account.sell_unlock,
2024-03-13 05:48:08,Sell SOL,SOL,-10.0,SGD,2050.00,USD,1525.46,1525.46,trading.limit_order.cash_account.sell_lock,
2024-01-05 10:00:00,Buy SOL,SOL,10.0,,,USD,1000,1000,crypto_purchase,
"""


def test_cryptocom_cancelled_limit_orders_ignored():
    parsed = cryptocom_csv.parse(LIMIT_ORDERS, "c.csv", 1)
    assert [(r.symbol, r.type, r.units) for r in parsed.records] == [("SOL", "SELL", 10.0), ("SOL", "BUY", 10.0)]
    assert any("limit order" in w for w in parsed.warnings)


def test_nri_crypto_and_nre_fd_not_taxed(fresh_db):
    import pandas as pd

    from core import tax

    df = pd.DataFrame([
        {"member_id": 1, "asset_class": "crypto", "category": "crypto", "buy_date": date(2025, 5, 1),
         "sell_date": date(2025, 6, 1), "gain": 100.0, "gain_inr": 8500.0},
    ])
    nri = tax.add_classification(df, {1: 0.3}, {1: "nri"})
    assert nri.iloc[0]["bucket"] == tax.BUCKET_NOT_TAXABLE
    assert tax.fy_summary(nri, 2025).iloc[0]["Est. tax (incl. cess)"] == 0
    resident = tax.add_classification(df, {1: 0.3}, {1: "resident"})
    assert tax.fy_summary(resident, 2025).iloc[0]["Taxable"] == pytest.approx(8500)
    assert not tax.fd_interest_taxable("nri", "nre")
    assert tax.fd_interest_taxable("nri", "nro")


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3

    from core import db

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE member (id INTEGER PRIMARY KEY, name VARCHAR(100), relation VARCHAR(50), pan_last4 VARCHAR(4), tax_slab FLOAT)")
    con.execute("INSERT INTO member (name, tax_slab) VALUES ('Old', 0.3)")
    con.commit()
    con.close()
    db.configure(f"sqlite:///{path.as_posix()}")
    from core.models import Member

    with db.session_scope() as s:
        assert s.query(Member).one().residency == "resident"
    db.get_engine().dispose()


def test_fd_snapshot_and_history(fresh_db):
    with session_scope() as s:
        s.add(FixedDeposit(member_id=1, bank="SBI", principal=100000, rate=7.0, start_date=date.today() - timedelta(days=200),
                           maturity_date=date.today() + timedelta(days=165), compounding="quarterly", payout="cumulative"))
    p = portfolio.load()
    s = p.summary()
    assert s.iloc[0]["asset_class"] == "fd"
    assert s.iloc[0]["value"] > 100000
    snapshot.take(p.as_of, p)
    assert snapshot.has_today()
    dates = snapshot.history_dates(date(2020, 1, 15), date(2025, 6, 1))
    assert dates[0] == date(2020, 1, 31) and dates[-1] == date(2025, 6, 1)
