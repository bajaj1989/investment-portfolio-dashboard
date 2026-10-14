"""Builds alert messages. Each alert has a key so it is sent at most once."""

from sqlalchemy import select

from core import goals as goalm
from core import tax
from core.config import ASSET_LABELS
from core.db import get_setting, session_scope
from core.fmt import inr, inr_short, money, pct
from core.models import AlertLog, Goal
from core.portfolio import Portfolio


def was_sent(key: str) -> bool:
    with session_scope() as s:
        return s.scalar(select(AlertLog.id).where(AlertLog.key == key)) is not None


def _mark(key: str):
    with session_scope() as s:
        s.add(AlertLog(key=key))


def daily_summary(p: Portfolio, errors: list[str]) -> str:
    s = p.summary()
    total, invested = s["value"].sum(), s["invested"].sum()
    day = float(p.holdings["day_change_inr"].sum()) if not p.holdings.empty else 0.0
    lines = [
        f"<b>Portfolio summary - {p.as_of:%d %b %Y}</b>",
        f"Net worth: <b>{inr_short(total)}</b> (invested {inr_short(invested)}, gain {inr_short(total - invested)})",
        f"Change since last price: {inr(day)}",
        f"Overall XIRR: {pct(p.xirr_for())}",
        "",
    ]
    for ac, g in s.groupby("asset_class"):
        line = f"{ASSET_LABELS.get(ac, ac)}: {inr_short(g['value'].sum())}"
        if ac == "crypto" and not p.holdings.empty:
            line += f" ({money(p.holdings[p.holdings['asset_class'] == 'crypto']['value'].sum(), 'USD')})"
        lines.append(line)
    if len(p.members) > 1:
        lines.append("")
        for m, g in s.groupby("member"):
            lines.append(f"{m}: {inr_short(g['value'].sum())}")
    if errors:
        lines += ["", "Price update problems: " + "; ".join(errors)]
    return "\n".join(lines)


def collect(p: Portfolio) -> list[tuple[str, str]]:
    """Returns (key, message) pairs for alerts that haven't been sent yet."""
    out = []
    today = p.as_of
    threshold = float(get_setting("alert_drop_pct") or 5) / 100

    h = p.holdings
    if not h.empty:
        moved = h[h["price"].notna() & (h["day_change"] != 0)].copy()
        if not moved.empty:
            moved["prev_value"] = moved["value"] - moved["day_change"]
            g = moved.groupby(["instrument_id", "name", "price_date", "currency"])[["value", "prev_value"]].sum().reset_index()
            for r in g.itertuples():
                change = r.value / r.prev_value - 1 if r.prev_value else 0
                if change <= -threshold:
                    out.append((f"drop:{r.instrument_id}:{r.price_date}",
                                f"Price drop: <b>{r.name}</b> {pct(change)} (now {money(r.value, r.currency, short=True)})"))

    if not p.fds.empty:
        for f in p.fds[p.fds["status"] == "active"].itertuples():
            days = f.days_to_maturity
            label = f"{f.bank} FD of {inr(f.principal)} ({f.member})"
            if days < 0:
                out.append((f"fdmatured:{f.id}", f"FD matured on {f.maturity_date:%d %b %Y}: {label}. Mark it closed or renewed in the dashboard."))
            else:
                for window in (1, 7, 30):
                    if days <= window:
                        out.append((f"fd{window}:{f.id}", f"FD maturing in {days} day(s) on {f.maturity_date:%d %b %Y}: {label}, maturity amount {inr(f.maturity_amount)}"))
                        break

    with session_scope() as s:
        goals = list(s.scalars(select(Goal)))
    for g in goals:
        progress = goalm.current_value(g, p) / g.target_amount if g.target_amount else 0
        for m in (100, 75, 50, 25):
            if progress * 100 >= m:
                out.append((f"goal:{g.id}:{m}", f"Goal <b>{g.name}</b> reached {m}% ({inr_short(goalm.current_value(g, p))} of {inr_short(g.target_amount)})"))
                break

    if today.month == 3 and not h.empty:
        fy = tax.fy_start(today)
        slabs = dict(zip(p.members["member_id"], p.members["tax_slab"]))
        residency = dict(zip(p.members["member_id"], p.members["residency"]))
        realised = tax.add_classification(p.realised, slabs, residency) if not p.realised.empty else p.realised
        eq = h[h["category"] == "equity"]
        for mid, g in eq.groupby("member_id"):
            gain = float(g["lt_unrealised_gain"].clip(lower=0).sum())
            mr = realised[realised["member_id"] == mid] if not realised.empty else realised
            left = tax.ltcg_exemption_left(mr, fy)
            if gain > 0 and left > 0:
                name = g["member"].iloc[0]
                out.append(
                    (f"ltcg:{fy}:{mid}:{today.isocalendar()[1]}",
                     f"Tax tip for {name}: {inr(min(gain, left))} of long-term equity gains can be booked tax-free before 31 March "
                     f"(exemption left {inr(left)}). See the Tax page.")
                )

    if today.day <= 3:
        out.append((f"monthly:{today:%Y-%m}", "Monthly reminder: download CAS statements (CAMS/KFintech), Zerodha tradebook and Crypto.com CSV, then import them on the Import page."))

    return [(k, m) for k, m in out if not was_sent(k)]


def mark_sent(keys: list[str]):
    for k in keys:
        _mark(k)
