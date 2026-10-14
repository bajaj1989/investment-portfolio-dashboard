from datetime import date

from sqlalchemy.dialects.sqlite import insert

from core.db import session_scope
from core.models import Price


def save_prices(rows: list[tuple[int, date, float]]) -> int:
    """Upsert (instrument_id, date, price) rows."""
    rows = [(i, d, float(p)) for i, d, p in rows if p is not None and p == p and p > 0]
    if not rows:
        return 0
    with session_scope() as s:
        for chunk in range(0, len(rows), 500):
            part = rows[chunk : chunk + 500]
            stmt = insert(Price).values([{"instrument_id": i, "date": d, "price": p} for i, d, p in part])
            stmt = stmt.on_conflict_do_update(index_elements=["instrument_id", "date"], set_={"price": stmt.excluded.price})
            s.execute(stmt)
    return len(rows)
