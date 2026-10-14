"""Manual transactions: corporate actions (bonus, split) and anything the statements miss."""
import uuid
from datetime import date

from importers.base import ParsedImport, Record

ACCOUNT_BY_CLASS = {
    "stock": ("zerodha", "ZERODHA", "Zerodha"),
    "mf": ("mf_folio", "MANUAL", "Mutual funds (manual)"),
    "crypto": ("cryptocom", "APP", "Crypto.com App"),
}


def single(
    member_id: int, asset_class: str, key: str, name: str, d: date, ttype: str, units: float, amount: float,
    fees: float = 0.0, tds: float = 0.0, note: str | None = None, symbol: str | None = None,
    isin: str | None = None, category: str | None = None, account: tuple[str, str, str] | None = None,
) -> ParsedImport:
    """account: (type, external_id, label) of an existing account; lots are matched per account."""
    acc_type, acc_ext, acc_label = account or ACCOUNT_BY_CLASS[asset_class]
    if asset_class != "crypto" and not isin and len(key) == 12 and key[:2].isalpha():
        isin = key
    ref = "man:" + uuid.uuid4().hex
    out = ParsedImport("manual", member_id, "manual entry", ref)
    out.records.append(
        Record(
            account_type=acc_type, account_id_ext=acc_ext, account_label=acc_label, asset_class=asset_class,
            inst_key=key, inst_name=name, symbol=symbol, isin=isin, category=category, date=d, type=ttype,
            units=units, amount=amount, fees=fees, tds=tds, note=note, ext_ref=ref,
            currency="USD" if asset_class == "crypto" else "INR",
        )
    )
    return out
