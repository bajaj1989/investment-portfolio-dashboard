from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st
from dateutil.relativedelta import relativedelta

from core import fd as fdm
from core import tax
from core.db import session_scope
from core.fmt import inr, inr_short
from core.models import FixedDeposit
from views import common

COMPOUNDING = {"quarterly": "Quarterly (most banks)", "monthly": "Monthly", "half_yearly": "Half-yearly", "yearly": "Yearly", "simple": "Simple interest (short FDs)"}
FD_TYPES = {"regular": "Regular (resident)", "nro": "NRO (taxable)", "nre": "NRE (tax-free interest)"}
PAYOUT = {"cumulative": "Cumulative (paid at maturity)", "monthly": "Monthly payout", "quarterly": "Quarterly payout", "half_yearly": "Half-yearly payout", "yearly": "Yearly payout"}

st.title("Fixed Deposits")
if common.need_members():
    st.stop()
ms = common.members()
member_names = {i: n for i, n in ms}


def fd_form(existing: FixedDeposit | None = None, key: str = "new"):
    e = existing
    with st.form(f"fd_form_{key}", clear_on_submit=existing is None):
        c = st.columns(4)
        member_id = c[0].selectbox("Member", [i for i, _ in ms], format_func=member_names.get,
                                   index=[i for i, _ in ms].index(e.member_id) if e else 0)
        bank = c[1].text_input("Bank", value=e.bank if e else "", placeholder="e.g. SBI, HDFC Bank")
        fd_type = c[2].selectbox("FD type", list(FD_TYPES), format_func=FD_TYPES.get,
                                 index=list(FD_TYPES).index(e.fd_type or "regular") if e else 0)
        fd_number = c[3].text_input("FD / account number (optional)", value=(e.fd_number or "") if e else "")
        c = st.columns(3)
        principal = c[0].number_input("Principal (₹)", min_value=0.0, step=1000.0, value=float(e.principal) if e else 100000.0)
        rate = c[1].number_input("Interest rate (% per year)", min_value=0.0, max_value=20.0, step=0.05, value=float(e.rate) if e else 7.0)
        start = c[2].date_input("Start date", value=e.start_date if e else date.today(), min_value=date(1990, 1, 1), format="DD/MM/YYYY")
        c = st.columns(3)
        months = c[0].number_input("Tenure months", min_value=0, max_value=240, value=0 if e else 12,
                                   help="Enter the tenure, or set it to 0 and pick the maturity date instead.")
        days = c[1].number_input("+ days", min_value=0, max_value=365, value=0)
        maturity = c[2].date_input("Maturity date (used when tenure is 0)", format="DD/MM/YYYY",
                                   value=e.maturity_date if e else date.today() + relativedelta(years=1))
        c = st.columns(3)
        comp = c[0].selectbox("Compounding", list(COMPOUNDING), format_func=COMPOUNDING.get,
                              index=list(COMPOUNDING).index(e.compounding) if e else 0)
        payout = c[1].selectbox("Interest payout", list(PAYOUT), format_func=PAYOUT.get,
                                index=list(PAYOUT).index(e.payout) if e else 0)
        tds = c[2].number_input("TDS deducted so far (₹)", min_value=0.0, step=100.0, value=float(e.tds_deducted) if e else 0.0)
        auto_renew = st.checkbox("Auto-renew at maturity", value=e.auto_renew if e else False)
        notes = st.text_area("Notes", value=(e.notes or "") if e else "", height=68)
        if st.form_submit_button("Save FD", type="primary"):
            mat = start + relativedelta(months=int(months), days=int(days)) if months or days else maturity
            if not bank.strip() or principal <= 0 or mat <= start:
                st.error("Please enter the bank, a principal above zero and a maturity date after the start date.")
                return
            with session_scope() as s:
                obj = s.get(FixedDeposit, e.id) if e else FixedDeposit()
                obj.member_id, obj.bank, obj.fd_number = member_id, bank.strip(), fd_number.strip() or None
                obj.fd_type = fd_type
                obj.principal, obj.rate, obj.start_date, obj.maturity_date = principal, rate, start, mat
                obj.compounding, obj.payout, obj.tds_deducted = comp, payout, tds
                obj.auto_renew, obj.notes = auto_renew, notes.strip() or None
                if not e:
                    s.add(obj)
            common.invalidate()
            st.success("FD saved.")
            st.rerun()


with st.expander("Add a fixed deposit", expanded=False, icon=":material/add:"):
    fd_form()

p = common.load()
fds = p.fds
if fds.empty:
    st.info("No FDs yet. Add one above.")
    st.stop()

active = fds[fds["status"] == "active"]
c = st.columns(4)
c[0].metric("Active FDs", len(active), border=True)
c[1].metric("Principal", inr_short(active["principal"].sum()), border=True)
c[2].metric("Current value", inr_short(active["value"].sum()), border=True)
c[3].metric("Interest this FY (accrued)", inr_short(active["interest_this_fy"].sum()), border=True)

matured = active[active["matured"]]
if not matured.empty:
    st.warning(f"{len(matured)} FD(s) have matured. Select them below and mark as closed or renewed.")

show_closed = st.toggle("Show closed FDs", value=False)
view = fds if show_closed else active
cols = ["member", "bank", "fd_type", "fd_number", "principal", "rate", "start_date", "maturity_date", "days_to_maturity", "value", "maturity_amount", "payout", "auto_renew", "status"]
st.dataframe(
    view[cols].sort_values("maturity_date"), hide_index=True,
    column_config={
        "principal": common.MONEY, "value": st.column_config.NumberColumn("Value now", format="₹ %,d"),
        "maturity_amount": st.column_config.NumberColumn("At maturity", format="₹ %,d"),
        "rate": st.column_config.NumberColumn("Rate %", format="%.2f"), "days_to_maturity": "Days left",
        "start_date": st.column_config.DateColumn("Start", format="DD MMM YYYY"),
        "maturity_date": st.column_config.DateColumn("Matures", format="DD MMM YYYY"),
    },
)
fd_labels = {
    int(r.id): f"{r.member} - {r.bank} {inr(r.principal)} (matures {r.maturity_date:%d %b %Y})"
    for r in view.sort_values("maturity_date").itertuples()
}
fid = st.selectbox("Manage an FD", [None] + list(fd_labels), format_func=lambda i: "Choose an FD..." if i is None else fd_labels[i])
if fid:
    with session_scope() as s:
        obj = s.get(FixedDeposit, fid)
    st.subheader(f"{obj.bank} - {inr(obj.principal)}")
    a, b, c_, d = st.columns(4)
    if obj.status == "active" and a.button("Mark closed", icon=":material/check_circle:"):
        with session_scope() as s:
            s.get(FixedDeposit, fid).status = "closed"
        common.invalidate()
        st.rerun()
    if obj.status == "closed" and a.button("Reopen", icon=":material/undo:"):
        with session_scope() as s:
            s.get(FixedDeposit, fid).status = "active"
        common.invalidate()
        st.rerun()
    with b.popover("Renew", icon=":material/autorenew:"):
        new_rate = st.number_input("New rate %", value=float(obj.rate), step=0.05, key="renew_rate")
        tenure = relativedelta(obj.maturity_date, obj.start_date)
        new_principal = st.number_input("New principal (₹)", value=round(fdm.maturity_amount(obj), 2) if obj.payout == "cumulative" else obj.principal, key="renew_p")
        if st.button("Create renewed FD", type="primary"):
            with session_scope() as s:
                old = s.get(FixedDeposit, fid)
                old.status = "closed"
                s.add(FixedDeposit(
                    member_id=old.member_id, bank=old.bank, fd_number=old.fd_number, fd_type=old.fd_type,
                    principal=new_principal, rate=new_rate,
                    start_date=old.maturity_date, maturity_date=old.maturity_date + tenure, compounding=old.compounding,
                    payout=old.payout, auto_renew=old.auto_renew, notes=f"Renewed from FD started {old.start_date:%d %b %Y}",
                ))
            common.invalidate()
            st.rerun()
    if c_.button("Delete", icon=":material/delete:"):
        with session_scope() as s:
            s.delete(s.get(FixedDeposit, fid))
        common.invalidate()
        st.rerun()
    with st.expander("Edit", icon=":material/edit:"):
        fd_form(obj, key=f"edit_{fid}")

st.subheader("Maturity calendar")
tl = active.copy()
tl["label"] = tl["bank"] + " " + tl["principal"].map(inr_short) + " (" + tl["member"] + ")"
fig = px.timeline(tl, x_start="start_date", x_end="maturity_date", y="label", color="member")
fig.add_vline(x=pd.Timestamp(date.today()).timestamp() * 1000, line_dash="dot")
fig.update_yaxes(title=None, autorange="reversed")
st.plotly_chart(fig, key="fd_timeline")

st.subheader("Interest by financial year")
st.caption("Accrued interest per member, bank and FD type. Regular FDs: banks deduct TDS above the threshold, and you can "
           "submit Form 15G/15H if your income is below the taxable limit. NRO FDs: TDS applies on all interest (no threshold, "
           "no 15G/15H). NRE FDs: interest is tax-free in India.")
fy_now = fdm.current_fy_start_year()
fy = st.selectbox("Financial year", list(range(fy_now + 1, fy_now - 6, -1)), index=1, format_func=tax.fy_label)
f0, f1 = fdm.fy_bounds(fy)
with session_scope() as s:
    objs = {f.id: f for f in s.query(FixedDeposit).all()}
rows = []
for r in fds.itertuples():
    rows.append({"member": r.member, "bank": r.bank, "type": r.fd_type.upper(), "interest": fdm.interest_between(objs[r.id], f0, f1)})
it = pd.DataFrame(rows).groupby(["member", "bank", "type"])["interest"].sum().reset_index()
it = it[it["interest"].abs() > 0.5]
threshold = tax.rules()["fd"]["tds_threshold"]
it["TDS applies"] = it.apply(lambda r: {"NRE": False, "NRO": True}.get(r["type"], r["interest"] > threshold), axis=1)
st.dataframe(it, hide_index=True, column_config={"interest": common.MONEY})
st.caption(f"TDS threshold used: {inr(threshold)} per bank per year ({inr(tax.rules()['fd']['tds_threshold_senior'])} for senior citizens).")
