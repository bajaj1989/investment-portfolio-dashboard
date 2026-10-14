"""Shared layout for the Stocks, Mutual Funds and Crypto pages."""
import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import delete

from core.db import get_engine, session_scope
from core.fmt import inr_short, money, pct
from core.models import Txn
from views import common


def render(asset_class: str, title: str):
    st.title(title)
    if common.need_members():
        st.stop()
    p = common.load()
    h = p.holdings[p.holdings["asset_class"] == asset_class] if not p.holdings.empty else p.holdings
    realised = p.realised[p.realised["asset_class"] == asset_class] if not p.realised.empty else p.realised
    if common.empty_df_note(h, title.lower()) and realised.empty:
        st.stop()

    cur = "USD" if asset_class == "crypto" else "INR"
    sym = "$" if cur == "USD" else "₹"
    big = st.column_config.NumberColumn(format=f"{sym} %,d")

    def short(x):
        return money(x, cur, short=True)

    if not h.empty:
        value, invested = h["value"].sum(), h["invested"].sum()
        c = st.columns(5)
        c[0].metric("Current value", short(value), border=True)
        c[1].metric("Invested", short(invested), border=True)
        c[2].metric("Unrealised gain", short(value - invested), pct(value / invested - 1) if invested else None, border=True)
        c[3].metric("XIRR", pct(p.xirr_for(common.member_ids(), [asset_class], native=True), signed=False),
                    help=f"Annualised return in {cur}.", border=True)
        c[4].metric("Realised gain (all time)", short(realised["gain"].sum() if not realised.empty else 0), border=True)
        if cur != "INR" and p.usd_inr:
            st.caption(f"Worth {inr_short(h['value_inr'].sum())} at today's rate of ₹{p.usd_inr:.2f} per US$ "
                       f"(cost {inr_short(h['invested_inr'].sum())} at the rates on purchase dates).")

        if h["price_missing"].any():
            st.warning("Some holdings have no price yet and are shown at cost: " + ", ".join(h[h["price_missing"]]["name"]))

        cols = ["member", "account", "name", "category", "units", "avg_cost", "price", "value", "invested", "pnl", "pnl_pct", "xirr", "first_buy"]
        if asset_class == "stock":
            cols.insert(4, "sector")
        if asset_class == "mf":
            cols.append("sip_active")
        if asset_class == "crypto":
            cols.remove("category")
        if common.member_ids() and len(common.member_ids()) == 1:
            cols.remove("member")
        st.dataframe(
            h[cols].sort_values("value", ascending=False),
            hide_index=True,
            column_config={
                "avg_cost": st.column_config.NumberColumn("Avg cost", format=f"{sym} %,.{4 if cur == 'USD' else 2}f"),
                "price": st.column_config.NumberColumn("Price", format=f"{sym} %,.{4 if cur == 'USD' else 2}f"),
                "value": st.column_config.NumberColumn("Value", format=f"{sym} %,d"),
                "invested": st.column_config.NumberColumn("Invested", format=f"{sym} %,d"),
                "pnl": st.column_config.NumberColumn("Gain", format=f"{sym} %,d"),
                "pnl_pct": st.column_config.NumberColumn("Gain %", format="percent"),
                "xirr": st.column_config.NumberColumn("XIRR", format="percent"),
                "units": st.column_config.NumberColumn("Units", format="%.4f" if asset_class != "stock" else "%d"),
                "first_buy": "Since",
                "sip_active": st.column_config.CheckboxColumn("Active SIP"),
            },
        )

        left, right = st.columns(2)
        agg = h.groupby("name")["value"].sum().reset_index()
        left.plotly_chart(px.treemap(agg, path=["name"], values="value", title="By holding"), key=f"tree_{asset_class}")
        group_col = {"stock": "sector", "mf": "category"}.get(asset_class)
        if group_col:
            g = h.assign(**{group_col: h[group_col].fillna("Unknown")}).groupby(group_col)["value"].sum().reset_index()
            right.plotly_chart(px.pie(g, names=group_col, values="value", hole=0.5, title=f"By {group_col}"), key=f"pie_{asset_class}")
        elif asset_class == "crypto" and not common.member_ids():
            g = h.groupby("member")["value"].sum().reset_index()
            right.plotly_chart(px.pie(g, names="member", values="value", hole=0.5, title="By member"), key="pie_crypto_member")

    if not realised.empty:
        with st.expander(f"Realised gains ({len(realised)} lots sold)"):
            if realised["missing_cost"].any():
                st.warning("Some sales have no matching purchase (older history missing), so their cost is treated as zero. Import older statements to fix this.")
            st.dataframe(
                realised[["member", "name", "buy_date", "sell_date", "units", "cost", "proceeds", "gain", "holding_days"]].sort_values("sell_date", ascending=False),
                hide_index=True,
                column_config={"cost": big, "proceeds": big, "gain": big},
            )

    _transactions(asset_class, big)


def _transactions(asset_class: str, money_col):
    with st.expander("Transactions"):
        q = """
            SELECT t.id, m.name AS member, a.label AS account, i.name, t.date, t.type, t.units, t.amount, t.fees, t.note, t.source
            FROM txn t JOIN account a ON a.id = t.account_id JOIN member m ON m.id = a.member_id
            JOIN instrument i ON i.id = t.instrument_id
            WHERE i.asset_class = :ac ORDER BY t.date DESC, t.id DESC
        """
        with get_engine().connect() as c:
            df = pd.read_sql(q, c, params={"ac": asset_class})
        if common.member_ids():
            names = [n for i, n in common.members() if i in common.member_ids()]
            df = df[df["member"].isin(names)]
        if df.empty:
            st.caption("No transactions.")
            return
        names = ["All"] + sorted(df["name"].unique())
        pick = st.selectbox("Instrument", names, key=f"txn_filter_{asset_class}")
        if pick != "All":
            df = df[df["name"] == pick]
        sel = st.dataframe(
            df, hide_index=True, on_select="rerun", selection_mode="multi-row", key=f"txn_table_{asset_class}",
            column_config={"id": None, "amount": money_col, "fees": money_col},
        )
        rows = sel.selection.rows if sel else []
        if rows:
            ids = [int(df.iloc[r]["id"]) for r in rows]
            st.caption(f"{len(ids)} selected. Deleted rows come back if you re-import the same statement.")
            if st.button(f"Delete {len(ids)} transaction(s)", type="secondary", icon=":material/delete:", key=f"del_{asset_class}"):
                with session_scope() as s:
                    s.execute(delete(Txn).where(Txn.id.in_(ids)))
                common.invalidate()
                st.rerun()
