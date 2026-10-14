"""Crypto prices in USD from CoinGecko's free public API."""
import logging
import time
from datetime import date, datetime, timezone

import requests
from sqlalchemy import select

from core.db import session_scope
from core.models import Instrument
from prices.store import save_prices

log = logging.getLogger(__name__)
API = "https://api.coingecko.com/api/v3"

KNOWN_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "CRO": "crypto-com-chain", "USDT": "tether", "USDC": "usd-coin",
    "SOL": "solana", "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token", "DOT": "polkadot", "LTC": "litecoin", "BNB": "binancecoin",
    "SHIB": "shiba-inu", "AVAX": "avalanche-2", "LINK": "chainlink", "TRX": "tron", "ATOM": "cosmos",
    "XLM": "stellar", "BCH": "bitcoin-cash", "UNI": "uniswap", "NEAR": "near", "APT": "aptos",
    "ARB": "arbitrum", "OP": "optimism", "PEPE": "pepe", "TON": "the-open-network", "SUI": "sui",
}


def _get(path: str, params: dict) -> dict | list:
    for attempt in range(3):
        r = requests.get(f"{API}{path}", params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return {}


def resolve_id(symbol: str) -> str | None:
    sym = symbol.upper()
    if sym in KNOWN_IDS:
        return KNOWN_IDS[sym]
    try:
        coins = _get("/search", {"query": sym}).get("coins", [])
    except requests.RequestException as e:
        log.warning("CoinGecko search failed for %s: %s", sym, e)
        return None
    exact = [c for c in coins if c.get("symbol", "").upper() == sym]
    ranked = sorted(exact, key=lambda c: c.get("market_cap_rank") or 10**9)
    return ranked[0]["id"] if ranked else None


def _coins() -> list[tuple[int, str]]:
    with session_scope() as s:
        out = []
        for inst in s.scalars(select(Instrument).where(Instrument.asset_class == "crypto")):
            if not inst.coingecko_id:
                inst.coingecko_id = resolve_id(inst.symbol or inst.key)
            if inst.coingecko_id:
                out.append((inst.id, inst.coingecko_id))
        return out


def update_latest() -> int:
    coins = _coins()
    if not coins:
        return 0
    ids = sorted({c for _, c in coins})
    data = _get("/simple/price", {"ids": ",".join(ids), "vs_currencies": "usd"})
    today = date.today()
    rows = [(inst_id, today, data[cid]["usd"]) for inst_id, cid in coins if cid in data and "usd" in data[cid]]
    return save_prices(rows)


def backfill_history(days: int = 365) -> int:
    """Daily USD prices for the last `days` (the free API allows up to 365)."""
    total = 0
    for inst_id, cid in _coins():
        try:
            data = _get(f"/coins/{cid}/market_chart", {"vs_currency": "usd", "days": min(days, 365), "interval": "daily"})
        except requests.RequestException as e:
            log.warning("CoinGecko history failed for %s: %s", cid, e)
            continue
        rows = [
            (inst_id, datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date(), p)
            for ms, p in data.get("prices", [])
        ]
        total += save_prices(rows)
        time.sleep(2.5)
    return total
