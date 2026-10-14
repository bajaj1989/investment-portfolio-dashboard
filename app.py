import streamlit as st

from core.db import configure

st.set_page_config(page_title="Family Portfolio", page_icon=":material/account_balance:", layout="wide")
configure()

from views import common  # noqa: E402  (needs the database configured first)

pages = {
    "Portfolio": [
        st.Page("views/overview.py", title="Overview", icon=":material/dashboard:", default=True),
        st.Page("views/stocks.py", title="Stocks", icon=":material/candlestick_chart:"),
        st.Page("views/mutual_funds.py", title="Mutual Funds", icon=":material/pie_chart:"),
        st.Page("views/crypto.py", title="Crypto", icon=":material/currency_bitcoin:"),
        st.Page("views/fixed_deposits.py", title="Fixed Deposits", icon=":material/account_balance:"),
    ],
    "Planning": [
        st.Page("views/tax.py", title="Tax", icon=":material/receipt_long:"),
        st.Page("views/goals.py", title="Goals", icon=":material/flag:"),
    ],
    "Data": [
        st.Page("views/import_data.py", title="Import", icon=":material/upload_file:"),
        st.Page("views/settings.py", title="Settings", icon=":material/settings:"),
    ],
}

nav = st.navigation(pages)
common.sidebar()
nav.run()
