import pandas as pd
import plotly.express as px
import streamlit as st

from core import snapshot
from core.config import ASSET_LABELS
from core.db import get_engine
from core.fmt import inr, inr_short, pct
from views import common

st.title("Overview")
if common.need_members():
    st.stop()

p = common.load()
s = p.summary()
if s.empty:
    st.info("No investments yet. Add FDs on the **Fixed Deposits** page or import statements on the **Import** page.")
    st.stop()

if not snapshot.has_today():
    snapshot.take()

total, invested = s["value"].sum(), s["invested"].sum()
day = float(p.holdings["day_change_inr"].sum()) if not p.holdings.empty else 0.0
c = st.columns(5)
c[0].metric("Net worth", inr_short(total), border=True)
c[1].metric("Invested", inr_short(invested), border=True)
c[2].metric("Gain", inr_short(total - invested), pct(total / invested - 1) if invested else None, border=True)
c[3].metric("XIRR", pct(p.xirr_for(), signed=False), help="Annualised return including all buys, sells, dividends and FDs.", border=True)
c[4].metric("Last price change", inr(day), help="Change in value since the previous price for each holding.", border=True)

stale = p.holdings[p.holdings["price_missing"]] if not p.holdings.empty else p.holdings
if not stale.empty:
    st.warning(f"{len(stale)} holding(s) have no price yet and are shown at cost. Click **Refresh prices now** in the sidebar.")
if p.usd_inr:
    st.caption(f"All amounts in ₹. Crypto (held in US$) is converted at ₹{p.usd_inr:.2f} per US$.")

left, right = st.columns(2)
by_class = s.groupby("asset_class")["value"].sum().reset_index()
by_class["Asset"] = by_class["asset_class"].map(ASSET_LABELS)
left.subheader("Allocation by asset class")
left.plotly_chart(px.pie(by_class, names="Asset", values="value", hole=0.5), key="pie_class")

risk = []
if not p.holdings.empty:
    h = p.holdings.copy()
    h["bucket"] = h.apply(lambda r: "Crypto" if r.asset_class == "crypto" else r.category.title(), axis=1)
    risk.append(h.groupby("bucket")["value_inr"].sum())
if not p.fds.empty:
    live = s[s["asset_class"] == "fd"]["value"].sum()
    risk.append(pd.Series({"Debt": live}))
risk_df = pd.concat(risk).groupby(level=0).sum().reset_index() if risk else pd.DataFrame(columns=["index", "value"])
risk_df.columns = ["Type", "value"]
right.subheader("Equity vs debt vs others")
right.plotly_chart(px.pie(risk_df, names="Type", values="value", hole=0.5), key="pie_risk")

if common.member_ids() is None and s["member"].nunique() > 1:
    st.subheader("By family member")
    bm = s.copy()
    bm["Asset"] = bm["asset_class"].map(ASSET_LABELS)
    st.plotly_chart(px.bar(bm, x="member", y="value", color="Asset", labels={"value": "Value (₹)", "member": ""}), key="bar_member")
st.subheader("Net worth history")
with get_engine().connect() as conn:
    hist = pd.read_sql("SELECT date, member_id, asset_class, invested, value FROM snapshot", conn, parse_dates=["date"])
if common.member_ids():
    hist = hist[hist["member_id"].isin(common.member_ids())]
if hist["date"].nunique() >= 2:
    hh = hist.groupby(["date", "asset_class"])["value"].sum().reset_index()
    hh["Asset"] = hh["asset_class"].map(ASSET_LABELS)
    fig = px.area(hh, x="date", y="value", color="Asset", labels={"value": "Value (₹)", "date": ""})
    inv = hist.groupby("date")["invested"].sum().reset_index()
    fig.add_scatter(x=inv["date"], y=inv["invested"], name="Invested", line=dict(color="black", dash="dot"))
    st.plotly_chart(fig, key="history")
else:
    st.caption("History builds up automatically each day. You can also rebuild it from past prices now.")
if st.button("Rebuild history from past prices", icon=":material/history:"):
    bar = st.progress(0.0, "Starting...")
    n = snapshot.rebuild_history(lambda f, m: bar.progress(min(f, 1.0), m))
    common.invalidate()
    st.success(f"Rebuilt {n} history points.")
    st.rerun()

col1, col2 = st.columns(2)
with col1:
    st.subheader("Upcoming FD maturities")
    if p.fds.empty:
        st.caption("No FDs added.")
    else:
        up = p.fds[(p.fds["status"] == "active") & (p.fds["days_to_maturity"] <= 90)].sort_values("maturity_date")
        if up.empty:
            st.caption("Nothing maturing in the next 90 days.")
        else:
            st.dataframe(
                up[["member", "bank", "maturity_date", "days_to_maturity", "maturity_amount"]],
                hide_index=True,
                column_config={"maturity_amount": common.MONEY, "maturity_date": "Matures", "days_to_maturity": "Days left"},
            )
with col2:
    st.subheader("Top holdings")
    if p.holdings.empty:
        st.caption("No stocks, mutual funds or crypto yet.")
    else:
        top = (p.holdings.groupby(["name", "asset_class"])[["value_inr", "pnl_inr"]].sum().reset_index()
               .rename(columns={"value_inr": "value", "pnl_inr": "pnl"}).nlargest(10, "value"))
        top["asset_class"] = top["asset_class"].map(ASSET_LABELS)
        st.dataframe(top, hide_index=True, column_config={"value": common.MONEY, "pnl": common.MONEY, "asset_class": "Type"})

st.subheader("Summary by asset class")
t = s.groupby("asset_class")[["invested", "value"]].sum().reset_index()
t["gain"] = t["value"] - t["invested"]
t["xirr"] = [p.xirr_for(common.member_ids(), [ac]) for ac in t["asset_class"]]
t["share"] = t["value"] / t["value"].sum()
t["asset_class"] = t["asset_class"].map(ASSET_LABELS)
st.dataframe(
    t, hide_index=True,
    column_config={"asset_class": "Asset", "invested": common.MONEY, "value": common.MONEY, "gain": common.MONEY, "xirr": common.PCT, "share": common.PCT},
)
