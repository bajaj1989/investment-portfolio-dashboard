from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from core import tax
from core.fmt import inr, inr_short
from core.holdings import build_position
from core.returns import xirr


def t(i, d, typ, units, amount, fees=0.0):
    return SimpleNamespace(id=i, date=d, type=typ, units=units, amount=amount, fees=fees)


def test_fifo_matching():
    pos = build_position([
        t(1, date(2023, 1, 1), "BUY", 10, 1000),
        t(2, date(2023, 6, 1), "BUY", 10, 2000),
        t(3, date(2024, 3, 1), "SELL", 15, 4500),
    ])
    assert pos.units == pytest.approx(5)
    assert pos.invested == pytest.approx(1000)
    assert [r.cost for r in pos.realised] == [pytest.approx(1000), pytest.approx(1000)]
    assert [r.proceeds for r in pos.realised] == [pytest.approx(3000), pytest.approx(1500)]
    assert pos.realised[0].buy_date == date(2023, 1, 1)


def test_split_and_bonus():
    pos = build_position([
        t(1, date(2023, 1, 1), "BUY", 10, 1000),
        t(2, date(2023, 2, 1), "SPLIT", 5, 0),
        t(3, date(2023, 3, 1), "BUY", 10, 0),
    ])
    assert pos.units == pytest.approx(60)
    assert pos.invested == pytest.approx(1000)


def test_sell_without_history_flags_missing_cost():
    pos = build_position([t(1, date(2024, 1, 1), "SELL", 5, 500)])
    assert pos.realised[0].missing_cost


def test_transfer_out_not_a_sale():
    pos = build_position([t(1, date(2024, 1, 1), "BUY", 2, 200), t(2, date(2024, 2, 1), "TRANSFER_OUT", 1, 150)])
    assert pos.units == pytest.approx(1)
    assert pos.realised == []


def test_classification():
    assert tax.classify("stock", "equity", date(2023, 1, 1), date(2024, 8, 1), 0.3) == (tax.BUCKET_EQ_LT, 0.125)
    assert tax.classify("stock", "equity", date(2023, 1, 1), date(2024, 1, 2), 0.3) == (tax.BUCKET_EQ_LT, 0.10)
    assert tax.classify("stock", "equity", date(2023, 3, 1), date(2024, 3, 1), 0.3)[0] == tax.BUCKET_EQ_ST
    assert tax.classify("mf", "equity", date(2024, 1, 1), date(2024, 9, 1), 0.3) == (tax.BUCKET_EQ_ST, 0.20)
    assert tax.classify("mf", "debt", date(2023, 5, 1), date(2026, 5, 1), 0.3) == (tax.BUCKET_SLAB, 0.3)
    assert tax.classify("mf", "debt", date(2020, 5, 1), date(2025, 5, 1), 0.3) == (tax.BUCKET_NE_LT, 0.125)
    assert tax.classify("crypto", "crypto", date(2020, 5, 1), date(2025, 5, 1), 0.3)[0] == tax.BUCKET_CRYPTO


def test_fy_summary_exemption_and_crypto_losses():
    df = pd.DataFrame([
        {"member_id": 1, "asset_class": "stock", "category": "equity", "buy_date": date(2023, 1, 1), "sell_date": date(2025, 6, 1), "gain": 200000.0},
        {"member_id": 1, "asset_class": "crypto", "category": "crypto", "buy_date": date(2025, 1, 1), "sell_date": date(2025, 6, 1), "gain": 10000.0},
        {"member_id": 1, "asset_class": "crypto", "category": "crypto", "buy_date": date(2025, 1, 1), "sell_date": date(2025, 7, 1), "gain": -8000.0},
    ])
    s = tax.fy_summary(tax.add_classification(df, {1: 0.3}), 2025).set_index("Category")
    assert s.at[tax.BUCKET_EQ_LT, "Taxable"] == pytest.approx(75000)
    assert s.at[tax.BUCKET_EQ_LT, "Est. tax (incl. cess)"] == pytest.approx(75000 * 0.125 * 1.04)
    assert s.at[tax.BUCKET_CRYPTO, "Taxable"] == pytest.approx(10000)


def test_xirr():
    r = xirr([(date(2024, 1, 1), -100000), (date(2025, 1, 1), 110000)])
    assert r == pytest.approx(0.10, abs=0.001)
    assert xirr([(date(2024, 1, 1), -100)]) is None


def test_amfi_parser_handles_old_and_new_layouts():
    from prices.amfi import _parse_nav_all

    text = (
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date\n"
        "Axis Mutual Fund\n"
        "135762;INF846K01WO1;-;Axis Children's Fund;Direct Plan;Growth Option;29.2309;13-Oct-2026\n"
        "119018;INF179K01YV8;-;HDFC Large Cap Fund - Direct Plan - Growth;1158.97;13-Oct-2026\n"
    )
    by_code, by_isin = _parse_nav_all(text)
    assert by_isin["INF846K01WO1"] == "135762"
    assert by_code["135762"][1] == pytest.approx(29.2309)
    assert by_code["119018"][0] == date(2026, 10, 13)


def test_inr_format():
    assert inr(12345678) == "₹1,23,45,678"
    assert inr(-999) == "-₹999"
    assert inr_short(2500000) == "₹25.00 L"
    assert inr_short(31000000) == "₹3.10 Cr"
