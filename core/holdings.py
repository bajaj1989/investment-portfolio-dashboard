"""Positions from transactions using FIFO lot matching (as required for Indian capital gains)."""
from dataclasses import dataclass, field
from datetime import date

EPS = 1e-9

_ORDER = {"SPLIT": 0, "BUY": 1, "DIVIDEND": 2, "FEE": 2, "SELL": 3, "TRANSFER_OUT": 3}


@dataclass
class Lot:
    date: date
    units: float
    cost_per_unit: float


@dataclass
class Realised:
    buy_date: date
    sell_date: date
    units: float
    cost: float
    proceeds: float
    missing_cost: bool = False

    @property
    def gain(self) -> float:
        return self.proceeds - self.cost

    @property
    def holding_days(self) -> int:
        return (self.sell_date - self.buy_date).days


@dataclass
class Position:
    lots: list[Lot] = field(default_factory=list)
    realised: list[Realised] = field(default_factory=list)
    dividends: float = 0.0

    @property
    def units(self) -> float:
        return sum(l.units for l in self.lots)

    @property
    def invested(self) -> float:
        return sum(l.units * l.cost_per_unit for l in self.lots)


def _consume(pos: Position, units: float) -> list[tuple[Lot, float]]:
    """Remove units FIFO; returns (lot, units_taken) pairs. Unmatched units return a None-dated lot."""
    taken = []
    while units > EPS and pos.lots:
        lot = pos.lots[0]
        q = min(lot.units, units)
        taken.append((Lot(lot.date, q, lot.cost_per_unit), q))
        lot.units -= q
        units -= q
        if lot.units <= EPS:
            pos.lots.pop(0)
    if units > EPS:
        taken.append((None, units))
    return taken


def build_position(txns) -> Position:
    """txns: objects with date, type, units, amount, fees, id (any order)."""
    pos = Position()
    for t in sorted(txns, key=lambda t: (t.date, _ORDER.get(t.type, 9), t.id or 0)):
        if t.type == "BUY":
            if t.units > EPS:
                pos.lots.append(Lot(t.date, t.units, (t.amount + (t.fees or 0)) / t.units))
        elif t.type == "SPLIT":
            ratio = t.units or 1.0
            for lot in pos.lots:
                lot.units *= ratio
                lot.cost_per_unit /= ratio
        elif t.type == "SELL":
            if t.units <= EPS:
                continue
            ppu = (t.amount - (t.fees or 0)) / t.units
            for lot, q in _consume(pos, t.units):
                if lot is None:
                    pos.realised.append(Realised(t.date, t.date, q, 0.0, q * ppu, missing_cost=True))
                else:
                    pos.realised.append(Realised(lot.date, t.date, q, q * lot.cost_per_unit, q * ppu))
        elif t.type == "TRANSFER_OUT":
            _consume(pos, t.units)
        elif t.type == "DIVIDEND":
            pos.dividends += t.amount
    return pos
