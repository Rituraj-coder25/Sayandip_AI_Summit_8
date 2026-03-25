"""Section 10a – Yahoo Finance (upgraded, expanded symbols, staggered batching, 5-min poll)."""
import asyncio
from datetime import UTC, datetime

from ...core.india.markets import publish_market_snapshot
from ..base_connector import BaseConnector

try:
    import yfinance as yf
except Exception:
    yf = None

EQUITY_SYMBOLS = ["^NSEI", "^BSESN", "^GSPC", "^DJI", "^IXIC", "^FTSE", "^GDAXI", "^FCHI", "^N225", "000001.SS", "^HSI"]
COMMODITY_SYMBOLS = ["GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F", "ZW=F", "ZS=F"]
FOREX_SYMBOLS = ["INR=X", "EURUSD=X", "GBPUSD=X", "JPY=X", "CNY=X", "SAR=X", "AED=X"]
GCC_INDICES = ["^TASI.SR", "^DFMGI.AE", "^ADI.AE", "^QSI.QA", "^MSM30.OM"]
ETF_SYMBOLS = ["IBIT", "FBTC", "GBTC", "ARKB", "HODL"]

ALL_SYMBOLS = EQUITY_SYMBOLS + COMMODITY_SYMBOLS + FOREX_SYMBOLS + GCC_INDICES + ETF_SYMBOLS
BATCH_SIZE = 5
BATCH_DELAY_MS = 200


class YahooFinanceConnector(BaseConnector):
    SOURCE_NAME = "yahoo_finance"
    POLL_INTERVAL_SECONDS = 300
    CACHE_TTL_SECONDS = 480

    async def fetch(self):
        if yf is None:
            return {}
        return await asyncio.to_thread(_fetch_quotes_batched)

    async def parse(self, payload):
        if not payload:
            return []
        now = datetime.now(UTC).isoformat()
        return [
            self.std_signal(
                id=f"yahoo-{symbol}",
                title=f"Market: {symbol} @ {data.get('price')}",
                summary=f"Last price {data.get('price')}, change {data.get('change_percent', 'N/A')}%",
                domain="economics",
                severity=30,
                india_score=25 if symbol in ("^NSEI", "^BSESN", "INR=X") else 5,
                url=f"https://finance.yahoo.com/quote/{symbol}",
                published_at=now,
                raw=data,
                tags=["markets", "yahoo", _symbol_category(symbol)],
            )
            for symbol, data in payload.items()
        ]

    async def post_process(self, items: list[dict]):
        if not items:
            return
        snapshot = {
            "NIFTY":  _extract_price(items, "^NSEI"),
            "SENSEX": _extract_price(items, "^BSESN"),
            "USDINR": _extract_price(items, "INR=X"),
        }
        await publish_market_snapshot(self.redis, snapshot)


def _fetch_quotes_batched():
    payload = {}
    for i in range(0, len(ALL_SYMBOLS), BATCH_SIZE):
        batch = ALL_SYMBOLS[i : i + BATCH_SIZE]
        for symbol in batch:
            try:
                ticker = yf.Ticker(symbol)
                fast_info = getattr(ticker, "fast_info", {}) or {}
                payload[symbol] = {
                    "symbol": symbol,
                    "price": fast_info.get("lastPrice") or fast_info.get("last_price"),
                    "change_percent": fast_info.get("regularMarketChangePercent") or fast_info.get("regular_market_change_percent"),
                }
            except Exception:
                payload[symbol] = {"symbol": symbol, "price": None, "change_percent": None}
        import time
        time.sleep(BATCH_DELAY_MS / 1000)
    return payload


def _symbol_category(symbol: str) -> str:
    if symbol in EQUITY_SYMBOLS or symbol in GCC_INDICES:
        return "equity"
    if symbol in COMMODITY_SYMBOLS:
        return "commodity"
    if symbol in FOREX_SYMBOLS:
        return "forex"
    if symbol in ETF_SYMBOLS:
        return "etf"
    return "other"


def _extract_price(items: list[dict], symbol: str):
    for item in items:
        if symbol in item.get("id", ""):
            return item.get("summary")
    return None
