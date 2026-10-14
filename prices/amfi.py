"""Mutual fund NAVs: latest from AMFI's NAVAll.txt, history from mfapi.in."""
import logging
from datetime import date, datetime

import requests
from sqlalchemy import select

from core.db import session_scope
from core.models import Instrument
from prices.store import save_prices

log = logging.getLogger(__name__)
NAV_ALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
MFAPI_URL = "https://api.mfapi.in/mf/{code}"


def _parse_nav_all(content: str) -> tuple[dict, dict]:
    """Returns ({amfi_code: (date, nav, name)}, {isin: amfi_code})."""
    by_code, by_isin = {}, {}
    for line in content.splitlines():
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        # Layout: code;isin1;isin2;name[;plan;option];nav;date
        code, isin1, isin2 = parts[:3]
        name = " - ".join(p for p in parts[3:-2] if p)
        nav, d = parts[-2], parts[-1]
        try:
            nav_f = float(nav)
            d_ = datetime.strptime(d, "%d-%b-%Y").date()
        except ValueError:
            continue
        by_code[code] = (d_, nav_f, name)
        for isin in (isin1, isin2):
            if isin and isin != "-":
                by_isin[isin] = code
    return by_code, by_isin


def update_latest() -> int:
    with session_scope() as s:
        funds = list(s.scalars(select(Instrument).where(Instrument.asset_class == "mf")))
    if not funds:
        return 0
    resp = requests.get(NAV_ALL_URL, timeout=60)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    by_code, by_isin = _parse_nav_all(resp.text)

    rows = []
    with session_scope() as s:
        for f in funds:
            inst = s.get(Instrument, f.id)
            code = inst.amfi_code or by_isin.get(inst.isin or "") or by_isin.get(inst.key)
            if code and not inst.amfi_code:
                inst.amfi_code = code
            if code and code in by_code:
                d, nav, _ = by_code[code]
                rows.append((inst.id, d, nav))
    return save_prices(rows)


def backfill_history(since: date) -> int:
    with session_scope() as s:
        funds = [(f.id, f.amfi_code) for f in s.scalars(select(Instrument).where(Instrument.asset_class == "mf")) if f.amfi_code]
    total = 0
    for inst_id, code in funds:
        try:
            data = requests.get(MFAPI_URL.format(code=code), timeout=60).json().get("data", [])
        except (requests.RequestException, ValueError) as e:
            log.warning("NAV history failed for %s: %s", code, e)
            continue
        rows = []
        for row in data:
            d = datetime.strptime(row["date"], "%d-%m-%Y").date()
            if d >= since:
                rows.append((inst_id, d, float(row["nav"])))
        total += save_prices(rows)
    return total
