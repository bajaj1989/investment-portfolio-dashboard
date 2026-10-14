# Family Portfolio Dashboard

Tracks stocks (Zerodha), mutual funds (CAMS/KFintech), crypto (Crypto.com App) and bank FDs for the whole family.
It runs only on this PC. Design: [docs/DESIGN.md](docs/DESIGN.md).

## Start the dashboard

Double-click **`start_dashboard.bat`**. Your browser opens at http://localhost:8501. Close the black window to stop it.

## First-time setup (about 15 minutes)

1. **Settings**: add yourself and family members, and choose each person's tax residency (Resident or NRI) and income tax slab.
2. **Fixed Deposits**: add each FD (bank, type Regular/NRO/NRE, amount, rate, start date, tenure).
3. **Import**: upload, for each family member:
   - **Mutual funds (CAS)**: the CAMS/KFintech *Detailed* statement PDF.
   - **Zerodha tradebook**: Console tradebook CSVs, one per year since you started.
   - **Crypto.com**: the App's *Crypto Wallet* transaction CSV.
4. Click **Refresh prices now** in the sidebar.
5. On **Overview**, click **Rebuild history from past prices** to draw your net-worth chart.
6. **Settings > Telegram alerts**: connect your Telegram bot (step-by-step instructions are on the page).
7. Double-click **`setup_scheduled_tasks.bat`** once, so prices, alerts and backups run automatically.

## Monthly routine

Download the month's statements (CAS, tradebook and Crypto.com CSV) and drop them on the **Import** page.
Re-importing a file is safe: rows already saved are skipped. A Telegram reminder arrives on the 1st of each month.

## Where things are

| What | Where |
|---|---|
| Your data | `data/portfolio.db` (never uploaded anywhere) |
| Backups | `data/backups/` by default; change it in Settings (e.g. to a OneDrive folder) |
| Passwords, API keys, Telegram token | Windows Credential Manager |
| Tax rates | `config/tax_rules.yaml` (update after each Budget) |
| Job log | `data/logs/jobs.log` |

## Known limits

- Bonus issues and stock splits aren't in Zerodha's tradebook. Add them under **Import > Manual entry**.
- Crypto.com App has no API, so crypto holdings update when you import a new CSV (prices update automatically).
- Crypto is shown in US$ on the Crypto page and converted to ₹ (daily USD/INR rate) in totals.
- For NRI members, crypto gains and NRE FD interest are treated as not taxable in India (see `config/tax_rules.yaml`).
- Tax figures are estimates: no surcharge, and losses are only set off within the same category. Confirm with your CA.

## For developers

```text
.venv\Scripts\python.exe -m pytest           # run tests
run_job.bat daily | crypto | backup | history # run a job manually
```
