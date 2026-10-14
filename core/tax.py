"""Capital gains classification and tax estimates under Indian rules (see config/tax_rules.yaml).

All tax maths uses INR amounts (`gain_inr` when present, so USD assets are converted at the
buy/sell date exchange rates).
"""
from datetime import date
from functools import lru_cache

import pandas as pd
import yaml

from core.config import TAX_RULES_PATH
from core.fd import add_months

BUCKET_EQ_ST = "Equity STCG"
BUCKET_EQ_LT = "Equity LTCG"
BUCKET_NE_LT = "Non-equity LTCG"
BUCKET_SLAB = "Slab rate (debt/other)"
BUCKET_CRYPTO = "Crypto (VDA)"
BUCKET_NOT_TAXABLE = "Not taxable in India (NRI)"


@lru_cache(maxsize=1)
def rules() -> dict:
    with open(TAX_RULES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def reload_rules():
    rules.cache_clear()


def fy_start(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def fy_label(start_year: int) -> str:
    return f"FY {start_year}-{str(start_year + 1)[-2:]}"


def _to_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def equity_period(sale: date) -> dict:
    periods = sorted(rules()["equity"]["periods"], key=lambda p: _to_date(p["effective_from"]))
    chosen = periods[0]
    for p in periods:
        if sale >= _to_date(p["effective_from"]):
            chosen = p
    return chosen


def is_long_term(buy: date, sale: date, months: int) -> bool:
    """Held for more than `months` calendar months."""
    return sale > add_months(buy, months)


def crypto_taxable(residency: str) -> bool:
    return residency != "nri" or bool(rules().get("nri", {}).get("crypto_taxable_in_india", False))


def fd_interest_taxable(residency: str, fd_type: str) -> bool:
    if fd_type == "nre":
        return bool(rules().get("nri", {}).get("nre_fd_interest_taxable", False))
    return True


def classify(asset_class: str, category: str, buy: date, sale: date, slab: float, residency: str = "resident") -> tuple[str, float]:
    """Return (bucket, tax rate) for one realised lot."""
    r = rules()
    if asset_class == "crypto":
        if not crypto_taxable(residency):
            return BUCKET_NOT_TAXABLE, 0.0
        return BUCKET_CRYPTO, r["crypto"]["rate"]
    if category == "equity":
        p = equity_period(sale)
        if is_long_term(buy, sale, r["equity"]["long_term_after_months"]):
            return BUCKET_EQ_LT, p["ltcg_rate"]
        return BUCKET_EQ_ST, p["stcg_rate"]
    ne = r["non_equity"]
    if buy >= _to_date(ne["slab_only_if_bought_on_or_after"]):
        return BUCKET_SLAB, slab
    if is_long_term(buy, sale, ne["long_term_after_months"]):
        return BUCKET_NE_LT, ne["ltcg_rate"]
    return BUCKET_SLAB, slab


def add_classification(realised: pd.DataFrame, slabs: dict[int, float], residency: dict[int, str] | None = None) -> pd.DataFrame:
    """realised needs: member_id, asset_class, category, buy_date, sell_date, gain (and gain_inr if non-INR)."""
    if realised.empty:
        return realised.assign(fy=pd.Series(dtype=int), bucket=pd.Series(dtype=str), rate=pd.Series(dtype=float),
                               taxable_gain=pd.Series(dtype=float))
    residency = residency or {}
    out = realised.copy()
    cls = [
        classify(r.asset_class, r.category, r.buy_date, r.sell_date, slabs.get(r.member_id, 0.3), residency.get(r.member_id, "resident"))
        for r in out.itertuples()
    ]
    out["bucket"] = [c[0] for c in cls]
    out["rate"] = [c[1] for c in cls]
    out["fy"] = [fy_start(d) for d in out["sell_date"]]
    out["taxable_gain"] = out["gain_inr"] if "gain_inr" in out.columns else out["gain"]
    return out


def fy_summary(df: pd.DataFrame, fy: int) -> pd.DataFrame:
    """Per-bucket gains (INR) and estimated tax for one member's realised lots in one FY.

    Simplifications: losses are netted within a bucket only (no cross-bucket set-off or
    carry-forward); crypto losses are ignored as required by Sec 115BBH.
    """
    r = rules()
    cess = r["cess"]
    rows = []
    d = df[df["fy"] == fy]
    for bucket in [BUCKET_EQ_ST, BUCKET_EQ_LT, BUCKET_NE_LT, BUCKET_SLAB, BUCKET_CRYPTO, BUCKET_NOT_TAXABLE]:
        b = d[d["bucket"] == bucket]
        if b.empty:
            continue
        g = b["taxable_gain"]
        gains = float(g.sum())
        exemption = 0.0
        if bucket == BUCKET_NOT_TAXABLE:
            taxable = tax = 0.0
        elif bucket == BUCKET_CRYPTO:
            taxable = float(g[g > 0].sum())
            tax = taxable * r["crypto"]["rate"]
        else:
            taxable = max(gains, 0.0)
            if bucket == BUCKET_EQ_LT:
                exemption = min(taxable, equity_period(date(fy + 1, 3, 31))["ltcg_exemption"])
                taxable -= exemption
            pos = g.clip(lower=0)
            weighted_rate = float((pos * b["rate"]).sum() / pos.sum()) if (g > 0).any() else 0.0
            tax = taxable * weighted_rate
        rows.append(
            {
                "Category": bucket,
                "Net gain": gains,
                "Exemption": exemption,
                "Taxable": taxable,
                "Est. tax (incl. cess)": tax * (1 + cess),
            }
        )
    return pd.DataFrame(rows)


def ltcg_exemption_left(df: pd.DataFrame, fy: int) -> float:
    exemption = equity_period(date(fy + 1, 3, 31))["ltcg_exemption"]
    if df.empty:
        return exemption
    used = float(df[(df["fy"] == fy) & (df["bucket"] == BUCKET_EQ_LT)]["taxable_gain"].sum())
    return max(exemption - max(used, 0.0), 0.0)
