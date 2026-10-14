"""Shared import pipeline: parsers produce records, the user previews them, commit() saves them."""
import hashlib
from dataclasses import dataclass, field
from datetime import date

import pandas as pd
from sqlalchemy import select

from core.db import session_scope
from core.models import Account, ImportLog, Instrument, Txn
from prices.store import save_prices


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_ref(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:32]


@dataclass
class Record:
    account_type: str
    account_id_ext: str
    account_label: str
    asset_class: str
    inst_key: str
    inst_name: str
    date: date
    type: str
    units: float
    amount: float
    ext_ref: str
    price: float = 0.0
    fees: float = 0.0
    tds: float = 0.0
    note: str | None = None
    symbol: str | None = None
    isin: str | None = None
    amfi_code: str | None = None
    category: str | None = None
    currency: str = "INR"  # currency of amount/price/fees


@dataclass
class ParsedImport:
    importer: str
    member_id: int
    file_name: str
    file_hash: str
    records: list[Record] = field(default_factory=list)
    # (asset_class, inst_key, date, price) e.g. valuation NAVs in a CAS statement
    prices: list[tuple[str, str, date, float]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def preview(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "Date": r.date, "Account": r.account_label, "Instrument": r.inst_name, "Type": r.type,
                    "Units": r.units, "Amount": r.amount, "Currency": r.currency, "Note": r.note,
                }
                for r in self.records
            ]
        )


def already_imported(h: str, member_id: int) -> bool:
    with session_scope() as s:
        return s.scalar(select(ImportLog.id).where(ImportLog.file_hash == h, ImportLog.member_id == member_id)) is not None


def _instrument(s, r: Record) -> Instrument:
    inst = s.scalar(select(Instrument).where(Instrument.asset_class == r.asset_class, Instrument.key == r.inst_key))
    if inst is None:
        if r.asset_class == "mf":
            from importers.cas_pdf import guess_category

            default_cat = guess_category(None, r.inst_name)
        else:
            default_cat = {"stock": "equity", "crypto": "crypto"}.get(r.asset_class, "other")
        inst = Instrument(
            asset_class=r.asset_class, key=r.inst_key, name=r.inst_name, symbol=r.symbol, isin=r.isin,
            amfi_code=r.amfi_code, category=r.category or default_cat, currency=r.currency,
        )
        s.add(inst)
        s.flush()
    else:
        inst.symbol = inst.symbol or r.symbol
        inst.amfi_code = inst.amfi_code or r.amfi_code
        inst.isin = inst.isin or r.isin
    return inst


def _account(s, member_id: int, r: Record) -> Account:
    acc = s.scalar(
        select(Account).where(Account.member_id == member_id, Account.type == r.account_type, Account.external_id == r.account_id_ext)
    )
    if acc is None:
        acc = Account(member_id=member_id, type=r.account_type, external_id=r.account_id_ext, label=r.account_label)
        s.add(acc)
        s.flush()
    return acc


def commit(parsed: ParsedImport) -> tuple[int, int]:
    """Save records, skipping ones already in the database. Returns (added, skipped)."""
    added = skipped = 0
    price_rows = []
    with session_scope() as s:
        existing = set(s.scalars(select(Txn.ext_ref).where(Txn.ext_ref.in_([r.ext_ref for r in parsed.records]))))
        inst_cache, acc_cache = {}, {}
        for r in parsed.records:
            if r.ext_ref in existing:
                skipped += 1
                continue
            ik = (r.asset_class, r.inst_key)
            if ik not in inst_cache:
                inst_cache[ik] = _instrument(s, r)
            ak = (r.account_type, r.account_id_ext)
            if ak not in acc_cache:
                acc_cache[ak] = _account(s, parsed.member_id, r)
            s.add(
                Txn(
                    account_id=acc_cache[ak].id, instrument_id=inst_cache[ik].id, date=r.date, type=r.type,
                    units=r.units, price=r.price or (r.amount / r.units if r.units else 0.0), amount=r.amount,
                    fees=r.fees, tds=r.tds, note=r.note, source=parsed.importer, ext_ref=r.ext_ref,
                )
            )
            existing.add(r.ext_ref)
            added += 1
        for ac, key, d, p in parsed.prices:
            inst = s.scalar(select(Instrument).where(Instrument.asset_class == ac, Instrument.key == key))
            if inst:
                price_rows.append((inst.id, d, p))
        s.add(
            ImportLog(
                file_hash=parsed.file_hash, file_name=parsed.file_name, importer=parsed.importer,
                member_id=parsed.member_id, rows_added=added, rows_skipped=skipped,
            )
        )
    save_prices(price_rows)
    return added, skipped
