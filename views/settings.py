import subprocess

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from core import tax
from core.config import BASE_DIR, TAX_RULES_PATH
from core.db import all_settings, session_scope, set_setting
from core.models import Account, FixedDeposit, Goal, Instrument, Member
from core.vault import get_secret, set_secret
from jobs import backup, telegram
from views import common

st.title("Settings")
SLABS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]

st.header("Family members")
with session_scope() as s:
    mem = pd.DataFrame(
        [{"id": m.id, "name": m.name, "relation": m.relation or "", "pan_last4": m.pan_last4 or "",
          "residency": m.residency or "resident", "tax_slab": m.tax_slab}
         for m in s.scalars(select(Member).order_by(Member.id))],
        columns=["id", "name", "relation", "pan_last4", "residency", "tax_slab"],
    )
if not mem.empty:
    edited = st.data_editor(
        mem, hide_index=True, key="members_editor", disabled=["id"],
        column_config={
            "id": None, "name": "Name", "relation": "Relation",
            "pan_last4": st.column_config.TextColumn("PAN (last 4 only)", max_chars=4),
            "residency": st.column_config.SelectboxColumn("Tax residency", options=["resident", "nri"],
                                                          help="NRI: crypto on foreign platforms and NRE FD interest are not taxed in India."),
            "tax_slab": st.column_config.SelectboxColumn("Income tax slab", options=SLABS, help="Marginal slab rate, used for debt fund, FD interest and dividend tax estimates."),
        },
    )
    if st.button("Save member changes"):
        with session_scope() as s:
            for r in edited.itertuples():
                m = s.get(Member, int(r.id))
                m.name, m.relation, m.pan_last4, m.tax_slab = r.name.strip(), r.relation or None, (r.pan_last4 or "")[-4:].upper() or None, float(r.tax_slab)
                m.residency = r.residency or "resident"
        common.invalidate()
        st.success("Saved.")
        st.rerun()

with st.form("add_member", clear_on_submit=True):
    st.markdown("**Add a family member**")
    c = st.columns(5)
    name = c[0].text_input("Name")
    relation = c[1].text_input("Relation", placeholder="Self, Spouse, Father...")
    pan4 = c[2].text_input("PAN last 4 (optional)", max_chars=4)
    res = c[3].selectbox("Tax residency", ["resident", "nri"], format_func={"resident": "Resident Indian", "nri": "NRI"}.get)
    slab = c[4].selectbox("Tax slab", SLABS, index=6, format_func=lambda x: f"{x:.0%}")
    if st.form_submit_button("Add member", type="primary"):
        if not name.strip():
            st.error("Enter a name.")
        elif not mem.empty and name.strip().lower() in mem["name"].str.lower().tolist():
            st.error("A member with this name already exists.")
        else:
            with session_scope() as s:
                s.add(Member(name=name.strip(), relation=relation.strip() or None, pan_last4=pan4.strip().upper() or None,
                             tax_slab=slab, residency=res))
            common.invalidate()
            st.rerun()

if not mem.empty:
    with st.expander("Remove a member"):
        rid = st.selectbox("Member", mem["id"].tolist(), format_func=lambda i: mem.set_index("id").at[i, "name"])
        with session_scope() as s:
            used = (s.scalar(select(func.count()).select_from(Account).where(Account.member_id == rid))
                    + s.scalar(select(func.count()).select_from(FixedDeposit).where(FixedDeposit.member_id == rid)))
        if used:
            st.caption("This member has accounts or FDs. Delete their transactions and FDs first.")
        elif st.button("Remove member", icon=":material/delete:"):
            with session_scope() as s:
                for g in s.scalars(select(Goal).where(Goal.member_id == rid)):
                    s.delete(g)
                s.delete(s.get(Member, rid))
            common.invalidate()
            st.rerun()

settings = all_settings()

st.header("Telegram alerts")
st.markdown(
    "1. In Telegram, open **@BotFather**, send `/newbot`, and follow the steps. It gives you a **token**.\n"
    "2. Paste the token below and save.\n"
    "3. Open your new bot in Telegram and send it any message (e.g. *hi*), then click **Find my chat ID**."
)
has_token = bool(get_secret("telegram_token"))
c = st.columns([3, 1])
token = c[0].text_input("Bot token", type="password", placeholder="saved" if has_token else "123456:ABC...")
if c[1].button("Save token", disabled=not token):
    set_secret("telegram_token", token.strip())
    st.rerun()
c = st.columns([3, 1, 1])
chat = c[0].text_input("Chat ID", value=settings["telegram_chat_id"])
if c[1].button("Find my chat ID", disabled=not has_token):
    try:
        found = telegram.find_chat_id(get_secret("telegram_token"))
        if found:
            set_setting("telegram_chat_id", found)
            st.rerun()
        else:
            st.warning("No messages found. Send your bot a message in Telegram first.")
    except Exception as e:
        st.error(f"Telegram error: {e}")
if c[2].button("Save chat ID"):
    set_setting("telegram_chat_id", chat.strip())
    st.rerun()
drop = st.number_input("Alert when a holding falls by at least (% in a day)", min_value=1.0, max_value=50.0,
                       value=float(settings["alert_drop_pct"]), step=0.5)
a, b = st.columns([1, 4])
if a.button("Save alert setting"):
    set_setting("alert_drop_pct", drop)
    st.success("Saved.")
if b.button("Send test message", disabled=not telegram.configured()):
    if telegram.send("Test message from your portfolio dashboard."):
        st.success("Sent! Check Telegram.")
    else:
        st.error("Sending failed; check token and chat ID.")

st.header("Automatic updates")
st.markdown(
    "Double-click **`setup_scheduled_tasks.bat`** in the project folder once. It creates Windows tasks that:\n"
    "- update prices, save the daily snapshot and send alerts every day at 7:00 AM and when you log in,\n"
    "- refresh crypto prices every hour,\n"
    "- back up the database weekly (as part of the daily job)."
)
try:
    out = subprocess.run(["schtasks", "/query", "/fo", "csv", "/nh"], capture_output=True, text=True, timeout=15).stdout
    tasks = [line.split(",")[0].strip('"') for line in out.splitlines() if "PortfolioDashboard" in line]
    if tasks:
        st.success("Scheduled tasks installed: " + ", ".join(sorted(set(tasks))))
    else:
        st.info("Scheduled tasks are not installed yet.")
except (OSError, subprocess.SubprocessError):
    pass
st.caption(f"Job log: `{BASE_DIR / 'data' / 'logs' / 'jobs.log'}`")

st.header("Backups")
c = st.columns([3, 1])
folder = c[0].text_input("Backup folder (e.g. inside your OneDrive folder)", value=settings["backup_dir"])
keep = c[1].number_input("Keep last", min_value=1, max_value=100, value=int(settings["backup_keep"]))
a, b = st.columns([1, 4])
if a.button("Save backup settings"):
    set_setting("backup_dir", folder.strip())
    set_setting("backup_keep", int(keep))
    st.success("Saved.")
if b.button("Back up now", icon=":material/backup:"):
    st.success(f"Saved to {backup.run()}")
last = backup.last_backup()
st.caption(f"Last backup: {last:%d %b %Y %H:%M}" if last else "No backups yet.")

st.header("Instruments")
st.caption("Fix how holdings are classified. Category drives tax treatment: only **equity** gets equity tax rates "
           "(set gold/liquid ETFs to gold/debt). For crypto, set the CoinGecko ID if prices are missing.")
with session_scope() as s:
    inst = pd.DataFrame(
        [{"id": i.id, "type": i.asset_class, "name": i.name, "key": i.key, "currency": i.currency, "symbol": i.symbol or "",
          "category": i.category, "coingecko_id": i.coingecko_id or "", "amfi_code": i.amfi_code or ""}
         for i in s.scalars(select(Instrument).where(Instrument.asset_class != "fx").order_by(Instrument.asset_class, Instrument.name))],
        columns=["id", "type", "name", "key", "currency", "symbol", "category", "coingecko_id", "amfi_code"],
    )
if inst.empty:
    st.caption("No instruments yet.")
else:
    ed = st.data_editor(
        inst, hide_index=True, key="inst_editor", disabled=["id", "type", "key", "currency"],
        column_config={
            "id": None,
            "category": st.column_config.SelectboxColumn("Category", options=["equity", "debt", "hybrid", "gold", "other", "crypto"]),
            "symbol": st.column_config.TextColumn("Symbol", help="NSE symbol for stocks"),
            "amfi_code": st.column_config.TextColumn("AMFI code", help="Mutual fund scheme code for NAVs"),
        },
    )
    if st.button("Save instrument changes"):
        with session_scope() as s:
            for r in ed.itertuples():
                i = s.get(Instrument, int(r.id))
                i.name, i.symbol, i.category = r.name, r.symbol or None, r.category
                i.coingecko_id, i.amfi_code = r.coingecko_id or None, r.amfi_code or None
        common.invalidate()
        st.success("Saved.")

st.header("Tax rules")
st.caption(f"Rates live in `{TAX_RULES_PATH}`. Edit the file after a Budget change, then click reload.")
if st.button("Reload tax rules"):
    tax.reload_rules()
    common.invalidate()
    st.success("Reloaded.")
