import io

import pandas as pd
import streamlit as st

from core import fd as fdm
from core import tax
from core.config import ASSET_LABELS
from core.db import get_engine, session_scope
from core.fmt import inr_short
from core.models import FixedDeposit
from views import common

st.title("Tax")
st.caption("Estimates based on config/tax_rules.yaml. Surcharge, cross-category loss set-off and carry-forward are not modelled. Confirm with your CA before filing.")
if common.need_members():
    st.stop()

p = common.load()
fy_now = tax.fy_start(p.as_of)
fy = st.selectbox("Financial year", list(range(fy_now, fy_now - 8, -1)), format_func=tax.fy_label)
f0, f1 = fdm.fy_bounds(fy)

slabs = dict(zip(p.members["member_id"], p.members["tax_slab"]))
residency = dict(zip(p.members["member_id"], p.members["residency"]))
realised = tax.add_classification(p.realised, slabs, residency) if not p.realised.empty else pd.DataFrame(
    columns=["member_id", "member", "asset_class", "name", "buy_date", "sell_date", "units", "cost_inr", "proceeds_inr",
             "gain_inr", "taxable_gain", "holding_days", "bucket", "rate", "fy", "missing_cost"]
)
fy_real = realised[realised["fy"] == fy]

with get_engine().connect() as c:
    divs = pd.read_sql(
        """SELECT m.id AS member_id, m.name AS member, i.name, t.date, t.amount, t.tds
           FROM txn t JOIN account a ON a.id=t.account_id JOIN member m ON m.id=a.member_id
           JOIN instrument i ON i.id=t.instrument_id
           WHERE t.type='DIVIDEND' AND t.date BETWEEN :a AND :b""",
        c, params={"a": f0.isoformat(), "b": f1.isoformat()},
    )
    crypto_tds = pd.read_sql(
        """SELECT m.id AS member_id, SUM(t.tds) AS tds FROM txn t JOIN account a ON a.id=t.account_id
           JOIN member m ON m.id=a.member_id JOIN instrument i ON i.id=t.instrument_id
           WHERE i.asset_class='crypto' AND t.date BETWEEN :a AND :b GROUP BY m.id""",
        c, params={"a": f0.isoformat(), "b": f1.isoformat()},
    )
with session_scope() as s:
    fd_objs = list(s.query(FixedDeposit).all())
fd_rows = [
    {"member_id": f.member_id, "bank": f.bank, "fd_type": (f.fd_type or "regular").upper(), "principal": f.principal,
     "interest": fdm.interest_between(f, f0, f1),
     "taxable": tax.fd_interest_taxable(residency.get(f.member_id, "resident"), f.fd_type or "regular")}
    for f in fd_objs
]
fd_int = pd.DataFrame(fd_rows, columns=["member_id", "bank", "fd_type", "principal", "interest", "taxable"])
fd_int = fd_int[fd_int["interest"].abs() > 0.5]

ids = common.member_ids() or list(p.members["member_id"])
cess = tax.rules()["cess"]
export = {}
for mid in ids:
    name = p.members.set_index("member_id").at[mid, "member"]
    slab = slabs.get(mid, 0.3)
    st.header(f"{name} - {tax.fy_label(fy)}")
    if residency.get(mid) == "nri":
        st.caption("NRI: crypto on foreign platforms and NRE FD interest are not taxed in India. "
                   "Indian stocks, mutual funds and NRO FD interest are, usually with TDS deducted at source.")
    mr = fy_real[fy_real["member_id"] == mid]
    summ = tax.fy_summary(mr, fy) if not mr.empty else pd.DataFrame()
    m_fd = fd_int[fd_int["member_id"] == mid]
    fd_tax, fd_free = m_fd[m_fd["taxable"]]["interest"].sum(), m_fd[~m_fd["taxable"]]["interest"].sum()
    m_div = divs[divs["member_id"] == mid]
    other = pd.DataFrame(
        [
            {"Category": "FD interest (slab)", "Net gain": fd_tax, "Exemption": 0.0, "Taxable": fd_tax,
             "Est. tax (incl. cess)": fd_tax * slab * (1 + cess)},
            {"Category": "NRE FD interest (tax-free)", "Net gain": fd_free, "Exemption": fd_free, "Taxable": 0.0,
             "Est. tax (incl. cess)": 0.0},
            {"Category": "Dividends (slab)", "Net gain": m_div["amount"].sum(), "Exemption": 0.0, "Taxable": m_div["amount"].sum(),
             "Est. tax (incl. cess)": m_div["amount"].sum() * slab * (1 + cess)},
        ]
    )
    other = other[other["Net gain"].abs() > 0.5]
    full = pd.concat([summ, other], ignore_index=True)
    if full.empty:
        st.caption("No capital gains, FD interest or dividends in this year.")
        continue
    c = st.columns(3)
    c[0].metric("Total taxable", inr_short(full["Taxable"].sum()), border=True)
    c[1].metric("Estimated tax", inr_short(full["Est. tax (incl. cess)"].sum()), border=True, help=f"Slab rate used: {slab:.0%} (change in Settings).")
    tds_c = float(crypto_tds[crypto_tds["member_id"] == mid]["tds"].sum()) if not crypto_tds.empty else 0.0
    c[2].metric("TDS already deducted", inr_short(tds_c + float(m_div["tds"].sum())), border=True, help="Crypto 1% TDS and dividend TDS recorded in imports. FD TDS is tracked per FD.")
    st.dataframe(full, hide_index=True, column_config={k: common.MONEY for k in ["Net gain", "Exemption", "Taxable", "Est. tax (incl. cess)"]})
    if not mr.empty:
        if mr["missing_cost"].any():
            st.warning("Some sales have no matching purchase in the data (history missing); their cost is taken as zero.")
        with st.expander("Capital gains detail (FIFO lots, in ₹)"):
            detail = mr[["name", "asset_class", "buy_date", "sell_date", "units", "cost_inr", "proceeds_inr", "gain_inr", "holding_days", "bucket"]].copy()
            detail["asset_class"] = detail["asset_class"].map(ASSET_LABELS)
            st.dataframe(detail.sort_values("sell_date"), hide_index=True,
                         column_config={"cost_inr": st.column_config.NumberColumn("Cost", format="₹ %,d"),
                                        "proceeds_inr": st.column_config.NumberColumn("Proceeds", format="₹ %,d"),
                                        "gain_inr": st.column_config.NumberColumn("Gain", format="₹ %,d")})
    export[name] = (full, mr, m_fd, m_div)

if fy == fy_now and not p.holdings.empty:
    st.header("Tax-free long-term gain booking")
    st.caption("Equity long-term gains up to the yearly exemption are tax-free. Selling and re-buying before 31 March "
               "resets your cost and uses this year's exemption.")
    rows = []
    for mid in ids:
        h = p.holdings[(p.holdings["member_id"] == mid) & (p.holdings["category"] == "equity")]
        lt = float(h["lt_unrealised_gain"].clip(lower=0).sum())
        left = tax.ltcg_exemption_left(realised[realised["member_id"] == mid], fy) if not realised.empty else tax.equity_period(p.as_of)["ltcg_exemption"]
        if lt > 0:
            rows.append({"Member": p.members.set_index("member_id").at[mid, "member"], "Unrealised long-term gain": lt,
                         "Exemption left": left, "Can book tax-free": min(lt, left)})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, column_config={k: common.MONEY for k in ["Unrealised long-term gain", "Exemption left", "Can book tax-free"]})
        cand = p.holdings[(p.holdings["category"] == "equity") & (p.holdings["lt_unrealised_gain"] > 0) & (p.holdings["member_id"].isin(ids))]
        st.dataframe(cand[["member", "name", "lt_unrealised_gain"]].sort_values("lt_unrealised_gain", ascending=False), hide_index=True,
                     column_config={"lt_unrealised_gain": st.column_config.NumberColumn("Long-term gain", format="₹ %,d")})
    else:
        st.caption("No unrealised long-term equity gains right now.")

if export:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, (full, mr, m_fd, m_div) in export.items():
            sheet = name[:18]
            full.to_excel(xw, sheet_name=f"{sheet} summary", index=False)
            if not mr.empty:
                mr.drop(columns=["member_id", "instrument_id", "category", "rate", "fy"], errors="ignore").to_excel(xw, sheet_name=f"{sheet} gains", index=False)
            if not m_fd.empty:
                m_fd.drop(columns=["member_id"]).to_excel(xw, sheet_name=f"{sheet} FD interest", index=False)
            if not m_div.empty:
                m_div.drop(columns=["member_id"]).to_excel(xw, sheet_name=f"{sheet} dividends", index=False)
    st.download_button("Download Excel for CA", buf.getvalue(), file_name=f"tax_{tax.fy_label(fy).replace(' ', '_')}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:")
