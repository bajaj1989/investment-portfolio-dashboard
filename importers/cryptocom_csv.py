"""Crypto.com App > Settings > Transaction history > Crypto wallet (CSV export).

Columns: Timestamp (UTC), Transaction Description, Currency, Amount, To Currency, To Amount,
Native Currency, Native Amount, Native Amount (in USD), Transaction Kind.
Each row can have up to two crypto legs (from Currency/Amount and To Currency/To Amount).
"""
import io

import pandas as pd

from importers.base import ParsedImport, Record, file_hash, make_ref

FIAT = {"INR", "USD", "EUR", "GBP", "AUD", "SGD", "CAD", "HKD", "JPY", "CHF", "AED", "BRL", "TRY"}

# Moves inside the app (Earn, lockups) - units don't leave the user's ownership.
INTERNAL_KINDS = {
    "lockup_lock", "lockup_unlock", "lockup_upgrade", "crypto_earn_program_created",
    "crypto_earn_program_withdrawn", "supercharger_deposit", "supercharger_withdrawal",
}
TRANSFER_OUT_KINDS = {"crypto_withdrawal", "crypto_to_exchange_transfer", "crypto_transfer"}
REWARD_HINTS = ("reward", "cashback", "interest", "referral", "bonus", "airdrop", "rebate", "reimbursement")


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "")) if pd.notna(v) and str(v).strip() else 0.0
    except ValueError:
        return 0.0


def parse(data: bytes, file_name: str, member_id: int) -> ParsedImport:
    df = pd.read_csv(io.BytesIO(data), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    needed = {"Timestamp (UTC)", "Currency", "Amount", "Native Currency", "Native Amount", "Transaction Kind"}
    if needed - set(df.columns):
        raise ValueError("This doesn't look like a Crypto.com App 'Crypto wallet' transaction CSV.")

    out = ParsedImport("cryptocom_csv", member_id, file_name, file_hash(data))
    df["_ts"] = pd.to_datetime(df["Timestamp (UTC)"])
    has_usd_col = "Native Amount (in USD)" in df.columns
    conv = None
    natives = set(df["Native Currency"].dropna().str.upper())
    if not has_usd_col and natives - {"USD", "INR"}:
        raise ValueError(f"This file is in {', '.join(sorted(natives))} without a 'Native Amount (in USD)' column; "
                         "please export it again from the Crypto.com App (the full export includes USD values).")
    if not has_usd_col and "INR" in natives:
        from prices import fx

        conv = fx.converter(df["_ts"].min().date())
        if conv is None:
            raise RuntimeError("Couldn't fetch USD/INR rates to convert this file; check your internet connection.")
        out.warnings.append("This file has no USD column; INR values were converted to USD at daily rates.")

    skipped_kinds = set()
    for _, row in df.iterrows():
        kind = str(row.get("Transaction Kind", "")).strip()
        if kind in INTERNAL_KINDS:
            skipped_kinds.add(kind)
            continue
        d = row["_ts"].date()
        if has_usd_col:
            value_usd = abs(_num(row["Native Amount (in USD)"]))
        elif str(row["Native Currency"]).upper() == "USD":
            value_usd = abs(_num(row["Native Amount"]))
        else:
            value_usd = abs(_num(row["Native Amount"])) / conv.rate(d)

        desc = str(row.get("Transaction Description", "") or kind)
        legs = [(str(row["Currency"]).upper(), _num(row["Amount"]))]
        if "To Currency" in df.columns and pd.notna(row.get("To Currency")):
            legs.append((str(row["To Currency"]).upper(), abs(_num(row.get("To Amount")))))

        for leg_no, (cur, amt) in enumerate(legs):
            if not cur or cur == "NAN" or cur in FIAT or amt == 0:
                continue
            if amt < 0:
                ttype = "TRANSFER_OUT" if kind in TRANSFER_OUT_KINDS else "SELL"
            else:
                ttype = "BUY"
            note = desc
            if ttype == "BUY" and any(h in kind.lower() or h in desc.lower() for h in REWARD_HINTS):
                note = f"Reward: {desc}"
            out.records.append(
                Record(
                    account_type="cryptocom", account_id_ext="APP", account_label="Crypto.com App",
                    asset_class="crypto", inst_key=cur, inst_name=cur, symbol=cur, category="crypto",
                    date=d, type=ttype, units=abs(amt), amount=value_usd, note=note, currency="USD",
                    ext_ref="cdc:" + make_ref(member_id, row["Timestamp (UTC)"], kind, cur, amt, leg_no),
                )
            )
    if skipped_kinds:
        out.warnings.append(f"Ignored internal moves: {', '.join(sorted(skipped_kinds))}.")
    if not out.records:
        out.warnings.append("No crypto transactions found in this file.")
    return out
