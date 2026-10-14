from datetime import date

import plotly.graph_objects as go
import streamlit as st
from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from core import goals as goalm
from core import portfolio
from core.config import ASSET_LABELS
from core.db import session_scope
from core.fmt import inr, inr_short
from core.models import Goal
from views import common

st.title("Goals")
if common.need_members():
    st.stop()
ms = common.members()
names = {None: "Whole family", **{i: n for i, n in ms}}

with st.expander("Add a goal", icon=":material/add:"):
    with st.form("goal_form", clear_on_submit=True):
        c = st.columns(3)
        name = c[0].text_input("Goal name", placeholder="e.g. Child's education")
        member = c[1].selectbox("For", list(names), format_func=names.get)
        target = c[2].number_input("Target amount (₹, today's value)", min_value=0.0, step=100000.0, value=2500000.0)
        c = st.columns(3)
        when = c[0].date_input("Target date", value=date.today() + relativedelta(years=10), format="DD/MM/YYYY")
        ret = c[1].number_input("Expected return % per year", value=10.0, step=0.5)
        classes = c[2].multiselect("Counts these investments", list(ASSET_LABELS), default=list(ASSET_LABELS), format_func=ASSET_LABELS.get)
        if st.form_submit_button("Save goal", type="primary"):
            if not name.strip() or target <= 0 or not classes:
                st.error("Please enter a name, a target and at least one investment type.")
            else:
                with session_scope() as s:
                    s.add(Goal(name=name.strip(), member_id=member, target_amount=target, target_date=when,
                               asset_classes=",".join(classes), expected_return=ret))
                st.rerun()

with session_scope() as s:
    goals = list(s.scalars(select(Goal).order_by(Goal.target_date)))
if not goals:
    st.info("No goals yet. Add one above.")
    st.stop()

p_all = portfolio.load()
for g in goals:
    current = goalm.current_value(g, p_all)
    months = goalm.months_left(g.target_date)
    need = goalm.required_monthly(g.target_amount, current, g.expected_return, months)
    progress = min(current / g.target_amount, 1.0) if g.target_amount else 0
    with st.container(border=True):
        top = st.columns([3, 1])
        top[0].subheader(g.name)
        top[0].caption(f"{names.get(g.member_id, '?')} · by {g.target_date:%b %Y} · counts {', '.join(ASSET_LABELS[c] for c in g.asset_classes.split(','))}")
        if top[1].button("Delete", key=f"del_goal_{g.id}", icon=":material/delete:"):
            with session_scope() as s:
                s.delete(s.get(Goal, g.id))
            st.rerun()
        st.progress(progress, text=f"{inr_short(current)} of {inr_short(g.target_amount)} ({progress:.0%})")
        c = st.columns(3)
        c[0].metric("Months left", months)
        c[1].metric("Monthly investment needed", inr(need), help=f"Assumes {g.expected_return:.1f}% annual return on current savings and new investments.")
        c[2].metric("Projected at this rate", inr_short(goalm.projection(current, need, g.expected_return, months)[-1]))
        if months > 0:
            proj = goalm.projection(current, need, g.expected_return, months)
            no_sip = goalm.projection(current, 0, g.expected_return, months)
            x = [date.today() + relativedelta(months=i) for i in range(months + 1)]
            fig = go.Figure()
            fig.add_scatter(x=x, y=proj, name="With monthly investment")
            fig.add_scatter(x=x, y=no_sip, name="Without new investment", line=dict(dash="dot"))
            fig.add_hline(y=g.target_amount, line_dash="dash", annotation_text="Target")
            fig.update_layout(height=280, margin=dict(t=10, b=10))
            st.plotly_chart(fig, key=f"goal_chart_{g.id}")
