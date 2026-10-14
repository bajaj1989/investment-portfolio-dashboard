from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import select

from core.db import get_engine, session_scope
from core.models import Account, Instrument
from core.vault import get_secret, set_secret
from importers import base, cas_pdf, cryptocom_csv, kite_api, manual, zerodha_tradebook
from views import common

st.title("Import")
if common.need_members():
    st.stop()
ms = common.members()
names = {i: n for i, n in ms}


def pick_member(key: str) -> int:
    default = common.member_ids()[0] if common.member_ids() else ms[0][0]
    ids = [i for i, _ in ms]
    return st.selectbox("Family member", ids, format_func=names.get, index=ids.index(default), key=f"member_{key}")


def pending_block(key: str):
    """Preview + confirm for a parsed import stored in session state."""
    parsed: base.ParsedImport | None = st.session_state.get(f"pending_{key}")
    if not parsed:
        return
    st.divider()
    st.subheader(f"Preview: {parsed.file_name}")
    for w in parsed.warnings:
        st.warning(w)
    if base.already_imported(parsed.file_hash, parsed.member_id):
        st.info("This exact file was imported before. Rows already in the database will be skipped.")
    prev = parsed.preview()
    if not prev.empty:
        c = st.columns(3)
        c[0].metric("Transactions", len(prev))
        c[1].metric("Instruments", prev["Instrument"].nunique())
        c[2].metric("Date range", f"{prev['Date'].min():%d %b %Y} - {prev['Date'].max():%d %b %Y}")
        st.dataframe(prev, hide_index=True, column_config={"Amount": st.column_config.NumberColumn(format="%,.2f")}, height=300)
    a, b = st.columns([1, 5])
    if a.button("Confirm import", type="primary", key=f"confirm_{key}", disabled=prev.empty):
        added, skipped = base.commit(parsed)
        st.session_state.pop(f"pending_{key}")
        common.invalidate()
        st.success(f"Imported {added} new transactions for {names[parsed.member_id]} ({skipped} already existed). "
                   "Click **Refresh prices now** in the sidebar to value them.")
    if b.button("Cancel", key=f"cancel_{key}"):
        st.session_state.pop(f"pending_{key}")
        st.rerun()


tabs = st.tabs(["Mutual funds (CAS)", "Zerodha tradebook", "Zerodha Kite API", "Crypto.com", "Manual entry", "Import history"])

with tabs[0]:
    st.markdown(
        "Get a **Detailed** Consolidated Account Statement covering all your funds:\n"
        "1. Open [CAMS CAS request](https://www.camsonline.com/Investors/Statements/Consolidated-Account-Statement) "
        "(or KFintech's MF Central).\n"
        "2. Choose **Detailed (includes transactions)**, period **Specific period** from your first investment to today, "
        "and **with zero balance folios**.\n"
        "3. Set a password, submit, and download the PDF from your email.\n\n"
        "Repeat for each family member (one statement per PAN)."
    )
    mid = pick_member("cas")
    f = st.file_uploader("CAS PDF", type=["pdf"], key="cas_file")
    saved_pw = get_secret(f"cas_password:{mid}") or ""
    pw = st.text_input("PDF password", value=saved_pw, type="password", key=f"cas_pw_{mid}")
    remember = st.checkbox("Remember password (stored in Windows Credential Manager)", value=bool(saved_pw), key="cas_remember")
    if st.button("Read statement", disabled=not (f and pw), key="cas_read"):
        try:
            with st.spinner("Reading statement..."):
                st.session_state["pending_cas"] = cas_pdf.parse(f.getvalue(), f.name, mid, pw)
            if remember:
                set_secret(f"cas_password:{mid}", pw)
        except ValueError as e:
            st.error(str(e))
    pending_block("cas")

with tabs[1]:
    st.markdown(
        "Download from [Zerodha Console](https://console.zerodha.com/reports/tradebook): **Reports > Tradebook**, "
        "segment **Equity**, choose a date range (max 1 year per download) and click the CSV icon. "
        "Download every year since you started trading and upload them all together."
    )
    mid = pick_member("zt")
    client_id = st.text_input("Zerodha client ID (optional, e.g. AB1234)", key="zt_client")
    files = st.file_uploader("Tradebook CSV files", type=["csv"], accept_multiple_files=True, key="zt_files")
    if st.button("Read tradebooks", disabled=not files, key="zt_read"):
        try:
            parts = [zerodha_tradebook.parse(x.getvalue(), x.name, mid, client_id) for x in files]
            merged = parts[0]
            for extra in parts[1:]:
                merged.records += extra.records
                merged.warnings += extra.warnings
            merged.file_name = ", ".join(x.name for x in files)
            seen, uniq = set(), []
            for r in merged.records:
                if r.ext_ref not in seen:
                    seen.add(r.ext_ref)
                    uniq.append(r)
            merged.records = uniq
            st.session_state["pending_zt"] = merged
        except ValueError as e:
            st.error(str(e))
    st.caption("Bonus issues and stock splits aren't in the tradebook. Add them under **Manual entry**.")
    pending_block("zt")

with tabs[2]:
    st.markdown(
        "Optional. Connects to Zerodha to **check holdings match** and fetch **live prices**. "
        "Needs a Kite Connect app (create one at [developers.kite.trade](https://developers.kite.trade) with redirect URL "
        "`http://127.0.0.1`). Zerodha requires a fresh login every day."
    )
    mid = pick_member("kite")
    key, secret = kite_api.creds(mid)
    if not key or not secret:
        with st.form("kite_creds"):
            k = st.text_input("API key")
            s_ = st.text_input("API secret", type="password")
            if st.form_submit_button("Save keys"):
                kite_api.save_creds(mid, k, s_)
                st.rerun()
    else:
        kite = kite_api.client(mid)
        if kite is None:
            st.link_button("1. Log in to Zerodha", kite_api.login_url(mid))
            url = st.text_input("2. After login you land on a page that won't load. Copy its full address (URL) and paste it here:")
            if st.button("Complete login", disabled=not url):
                try:
                    kite_api.complete_login(mid, url)
                    st.rerun()
                except Exception as e:  # kiteconnect raises its own exception types
                    st.error(f"Login failed: {e}")
        else:
            st.success("Logged in to Kite for today.")
            try:
                kh = kite_api.holdings(mid)
            except Exception as e:
                st.error(f"Couldn't fetch holdings: {e}")
                kh = pd.DataFrame()
            if not kh.empty:
                n = kite_api.save_live_prices(kh)
                if n:
                    common.invalidate()
                p = common.load()
                mine = p.holdings[(p.holdings["member_id"] == mid) & (p.holdings["asset_class"] == "stock")] if not p.holdings.empty else pd.DataFrame(columns=["isin", "units"])
                ours = mine.groupby("isin")["units"].sum().rename("dashboard_units").reset_index()
                rec = kh.merge(ours, on="isin", how="outer")
                rec["symbol"] = rec["symbol"].fillna(rec["isin"])
                rec[["kite_units", "dashboard_units"]] = rec[["kite_units", "dashboard_units"]].fillna(0)
                rec["matches"] = (rec["kite_units"] - rec["dashboard_units"]).abs() < 1e-6
                st.dataframe(rec[["symbol", "isin", "kite_units", "dashboard_units", "avg_price", "last_price", "matches"]], hide_index=True)
                missing = rec[(rec["dashboard_units"] == 0) & (rec["kite_units"] > 0)]
                if not rec["matches"].all():
                    st.warning("Some holdings don't match. Import older tradebooks, or add bonus/split entries under Manual entry.")
                if not missing.empty:
                    st.markdown("**Stocks with no trade history in the dashboard** can be added at Kite's average price "
                                "(tax and XIRR will be approximate for these):")
                    pick = st.multiselect("Stocks", missing["isin"].tolist(), default=missing["isin"].tolist(),
                                          format_func=lambda i: rec.set_index("isin").at[i, "symbol"])
                    as_of = st.date_input("Treat as bought on", value=date(date.today().year - 1, 4, 1), format="DD/MM/YYYY")
                    if st.button("Add as opening balance", disabled=not pick):
                        added, _ = base.commit(kite_api.opening_balance(kh, mid, as_of, pick))
                        common.invalidate()
                        st.success(f"Added {added} holdings.")
        if st.button("Change API keys", type="tertiary"):
            from core.vault import delete_secret

            for n in ("kite_api_key", "kite_api_secret", "kite_access_token"):
                delete_secret(f"{n}:{mid}")
            st.rerun()

with tabs[3]:
    st.markdown(
        "In the **Crypto.com App**: Settings > Transaction History (or Account > History) > Export > **Crypto Wallet**, "
        "choose the full date range, and the CSV is emailed to you. Upload it here."
    )
    mid = pick_member("cdc")
    f = st.file_uploader("Crypto.com CSV", type=["csv"], key="cdc_file")
    if st.button("Read CSV", disabled=not f, key="cdc_read"):
        try:
            with st.spinner("Reading..."):
                st.session_state["pending_cdc"] = cryptocom_csv.parse(f.getvalue(), f.name, mid)
        except (ValueError, RuntimeError) as e:
            st.error(str(e))
    st.caption("Amounts are recorded in US$ (from the file's USD column). Rewards and cashback are added at their market "
               "value on the day received. Withdrawals to other wallets remove coins without counting as a sale.")
    pending_block("cdc")

with tabs[4]:
    st.markdown("Add bonus shares, stock splits, or any purchase/sale missing from your statements.")
    mid = pick_member("man")
    ac = st.selectbox("Investment type", ["stock", "mf", "crypto"], format_func={"stock": "Stock", "mf": "Mutual fund", "crypto": "Crypto"}.get)
    with session_scope() as s:
        insts = list(s.scalars(select(Instrument).where(Instrument.asset_class == ac).order_by(Instrument.name)))
        accs = list(s.scalars(select(Account).where(Account.member_id == mid)))
    acc_types = {"stock": "zerodha", "mf": "mf_folio", "crypto": "cryptocom"}
    accs = [a for a in accs if a.type == acc_types[ac]]
    opts = ["(new)"] + [i.id for i in insts]
    inst_labels = {i.id: f"{i.name} ({i.key})" for i in insts}
    pick = st.selectbox("Instrument", opts, format_func=lambda o: "New instrument..." if o == "(new)" else inst_labels[o])
    if pick == "(new)":
        c = st.columns(2)
        new_name = c[0].text_input("Name", placeholder="e.g. RELIANCE or BTC")
        new_key = c[1].text_input("ISIN (stocks/funds) or symbol (crypto)")
        symbol = st.text_input("NSE symbol (stocks)") if ac == "stock" else None
    acc = st.selectbox("Account", accs, format_func=lambda a: a.label) if accs else None
    kind = st.selectbox("Type", ["BUY", "SELL", "DIVIDEND", "BONUS", "SPLIT"],
                        format_func={"BUY": "Buy", "SELL": "Sell", "DIVIDEND": "Dividend received", "BONUS": "Bonus shares", "SPLIT": "Split (ratio)"}.get)
    c = st.columns(4)
    d = c[0].date_input("Date", value=date.today(), format="DD/MM/YYYY")
    units_label = {"SPLIT": "New shares per old share (e.g. 5 for 1:5)", "BONUS": "Bonus shares received", "DIVIDEND": "Units (leave 0)"}.get(kind, "Units")
    units = c[1].number_input(units_label, min_value=0.0, step=1.0, format="%.6f")
    cur_sym = "US$" if ac == "crypto" else "₹"
    amount = c[2].number_input(f"Total amount ({cur_sym})", min_value=0.0, step=100.0, disabled=kind in ("SPLIT", "BONUS"))
    fees = c[3].number_input(f"Charges / TDS ({cur_sym})", min_value=0.0, step=10.0)
    note = st.text_input("Note")
    if st.button("Add transaction", type="primary"):
        if pick == "(new)" and not (new_name.strip() and new_key.strip()):
            st.error("Enter a name and ISIN/symbol for the new instrument.")
        elif units <= 0 and kind != "DIVIDEND":
            st.error("Enter the number of units.")
        else:
            if pick == "(new)":
                key_, name_ = new_key.strip().upper(), new_name.strip()
                sym = (symbol or "").strip().upper() or (key_ if ac == "crypto" else None)
                isin = key_ if ac != "crypto" else None
            else:
                inst = next(i for i in insts if i.id == pick)
                key_, name_, sym, isin = inst.key, inst.name, inst.symbol, inst.isin
            ttype = {"BONUS": "BUY"}.get(kind, kind)
            parsed = manual.single(
                mid, ac, key_, name_, d, ttype, units, 0.0 if kind in ("BONUS", "SPLIT") else amount,
                fees=fees if kind != "DIVIDEND" else 0.0, tds=fees if kind == "DIVIDEND" else 0.0,
                note=note or ("Bonus issue" if kind == "BONUS" else None), symbol=sym, isin=isin,
                account=(acc.type, acc.external_id, acc.label) if acc else None,
            )
            base.commit(parsed)
            common.invalidate()
            st.success("Transaction added.")

with tabs[5]:
    with get_engine().connect() as c:
        log = pd.read_sql(
            """SELECT l.imported_at, m.name AS member, l.importer, l.file_name, l.rows_added, l.rows_skipped
               FROM import_log l LEFT JOIN member m ON m.id = l.member_id WHERE l.importer != 'manual'
               ORDER BY l.imported_at DESC""", c)
    if log.empty:
        st.caption("Nothing imported yet.")
    else:
        st.dataframe(log, hide_index=True)
