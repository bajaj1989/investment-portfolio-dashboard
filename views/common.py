from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from core import portfolio
from core.db import session_scope
from core.models import Member, Price

MONEY = st.column_config.NumberColumn(format="₹ %,d")
PCT = st.column_config.NumberColumn(format="percent")


def members() -> list[tuple[int, str]]:
    with session_scope() as s:
        return [(m.id, m.name) for m in s.scalars(select(Member).order_by(Member.id))]


def sidebar():
    ms = members()
    with st.sidebar:
        if ms:
            names = ["Whole family"] + [n for _, n in ms]
            choice = st.selectbox("Show portfolio of", names, key="member_choice")
            st.session_state["member_ids"] = None if choice == "Whole family" else [i for i, n in ms if n == choice]
        else:
            st.session_state["member_ids"] = None
        if st.button("Refresh prices now", icon=":material/refresh:", width="stretch"):
            refresh_prices()
        with session_scope() as s:
            last = s.scalar(select(func.max(Price.date)))
        st.caption(f"Latest price date: {last:%d %b %Y}" if last else "No prices yet")
        msg = st.session_state.pop("refresh_msg", None)
        if msg:
            (st.warning if msg.startswith("Some") else st.success)(msg)


def refresh_prices():
    from core import snapshot
    from jobs.daily_job import update_prices

    with st.spinner("Fetching latest NAVs and prices..."):
        errors = update_prices()
        snapshot.take()
    invalidate()
    st.session_state["refresh_msg"] = "Some prices failed: " + "; ".join(errors) if errors else "Prices updated"


def member_ids() -> list[int] | None:
    return st.session_state.get("member_ids")


@st.cache_data(ttl=600, show_spinner="Calculating portfolio...")
def _load(ids: tuple | None, as_of: date) -> portfolio.Portfolio:
    return portfolio.load(list(ids) if ids else None, as_of)


def load() -> portfolio.Portfolio:
    ids = member_ids()
    return _load(tuple(ids) if ids else None, date.today())


def invalidate():
    st.cache_data.clear()


def need_members() -> bool:
    """Shows a hint and returns True if no family members exist yet."""
    if not members():
        st.info("Start by adding yourself and your family members on the **Settings** page.")
        st.page_link("views/settings.py", label="Go to Settings", icon=":material/settings:")
        return True
    return False


def empty_df_note(df: pd.DataFrame, what: str) -> bool:
    if df is None or df.empty:
        st.info(f"No {what} yet. Add data on the **Import** page.")
        st.page_link("views/import_data.py", label="Go to Import", icon=":material/upload_file:")
        return True
    return False
