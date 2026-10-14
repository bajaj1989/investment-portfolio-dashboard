"""CAMS / KFintech Consolidated Account Statement (DETAILED) PDF via casparser."""
import io
from datetime import date

import casparser
from casparser.exceptions import IncorrectPasswordError, ParserException
from casparser.types import CASData

from importers.base import ParsedImport, Record, file_hash, make_ref

BUY_TYPES = {"PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "SWITCH_IN_MERGER", "DIVIDEND_REINVEST", "GIFT_IN"}
SELL_TYPES = {"REDEMPTION", "SWITCH_OUT", "SWITCH_OUT_MERGER"}
TAX_TYPES = {"STT_TAX", "STAMP_DUTY_TAX", "TDS_TAX"}

DEBT_HINTS = ("liquid", "debt", "bond", "gilt", "overnight", "money market", "corporate", "duration", "credit", "banking & psu", "floater")
EQUITY_HINTS = ("equity", "elss", "tax saver", "nifty", "sensex", "index", "flexi", "large cap", "mid cap", "small cap", "multi cap", "focused", "value", "bluechip", "arbitrage")


def guess_category(scheme_type: str | None, name: str) -> str:
    n = name.lower()
    if "gold" in n or "silver" in n:
        return "gold"
    if "fund of fund" in n or "fof" in n.split():
        return "other"
    if scheme_type == "EQUITY":
        return "equity"
    if scheme_type == "DEBT":
        return "debt"
    if "hybrid" in n or "balanced" in n or "asset allocation" in n:
        return "hybrid"
    if any(h in n for h in DEBT_HINTS):
        return "debt"
    if any(h in n for h in EQUITY_HINTS):
        return "equity"
    return "other"


def _d(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def parse(data: bytes, file_name: str, member_id: int, password: str) -> ParsedImport:
    try:
        cas = casparser.read_cas_pdf(io.BytesIO(data), password)
    except IncorrectPasswordError as e:
        raise ValueError("Wrong PDF password. CAS statements use the password you chose when requesting them.") from e
    except ParserException as e:
        raise ValueError(f"Could not read the statement: {e}") from e

    if not isinstance(cas, CASData):
        raise ValueError("This is an NSDL/CDSL demat statement. Please upload a CAMS or KFintech CAS (Detailed) instead.")
    cas_type = getattr(cas.cas_type, "value", cas.cas_type)
    if cas_type != "DETAILED":
        raise ValueError("This is a SUMMARY statement. Please request the DETAILED statement (with transactions) from CAMS/KFintech.")

    out = ParsedImport("cas_pdf", member_id, file_name, file_hash(data))
    out.warnings.extend(cas.parse_warnings)

    for folio in cas.folios:
        acc_label = f"{folio.amc} - {folio.folio}"
        for sch in folio.schemes:
            key = sch.isin or (f"AMFI:{sch.amfi}" if sch.amfi else sch.scheme)
            category = guess_category(sch.type, sch.scheme)
            base = dict(
                account_type="mf_folio", account_id_ext=folio.folio, account_label=acc_label, asset_class="mf",
                inst_key=key, inst_name=sch.scheme, isin=sch.isin, amfi_code=sch.amfi, category=category,
            )
            for n, t in enumerate(sch.transactions):
                ttype = str(getattr(t.type, "value", t.type))
                units = _f(t.units)
                nav = _f(t.nav)
                amount = abs(_f(t.amount)) or abs(units) * nav
                if ttype in TAX_TYPES:
                    kind = "FEE"
                elif ttype == "DIVIDEND_PAYOUT":
                    kind = "DIVIDEND"
                elif ttype in BUY_TYPES:
                    kind = "BUY"
                elif ttype in SELL_TYPES:
                    kind = "SELL"
                elif ttype == "GIFT_OUT":
                    kind = "TRANSFER_OUT"
                elif units > 0:
                    kind = "BUY"
                elif units < 0:
                    kind = "SELL"
                else:
                    continue
                note = t.description.strip()
                if ttype == "PURCHASE_SIP" and "SIP" not in note.upper():
                    note = f"SIP {note}"
                out.records.append(
                    Record(
                        **base, date=_d(t.date), type=kind, units=abs(units) if kind != "FEE" else 0.0,
                        price=nav, amount=amount, note=note[:300],
                        ext_ref="cas:" + make_ref(member_id, folio.folio, key, t.date, ttype, t.units, t.amount, t.balance, n if t.balance is None else ""),
                    )
                )
            if sch.valuation and sch.valuation.nav:
                out.prices.append(("mf", key, _d(sch.valuation.date), _f(sch.valuation.nav)))
    if not out.records:
        out.warnings.append("No transactions found in this statement.")
    return out
