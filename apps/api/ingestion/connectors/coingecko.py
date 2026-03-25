"""Section 10b – CoinGecko Crypto Markets (upgraded, 5-min poll)."""
from datetime import UTC, datetime

from ...config import settings
from ..base_connector import BaseConnector


class CoinGeckoConnector(BaseConnector):
    SOURCE_NAME = "coingecko_markets"
    POLL_INTERVAL_SECONDS = 300
    CACHE_TTL_SECONDS = 300

    async def fetch(self):
        results = {}
        headers = {}
        if settings.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = settings.COINGECKO_API_KEY

        # Market data
        try:
            results["markets"] = await self.fetch_json(
                "https://api.coingecko.com/api/v3/coins/markets"
                "?vs_currency=usd&ids=bitcoin,ethereum,solana,ripple,tether,usd-coin,dai",
                headers=headers
            )
        except Exception:
            results["markets"] = None
        # Trending
        try:
            results["trending"] = await self.fetch_json(
                "https://api.coingecko.com/api/v3/search/trending",
                headers=headers
            )
        except Exception:
            results["trending"] = None
        # Global stats
        try:
            results["global"] = await self.fetch_json(
                "https://api.coingecko.com/api/v3/global",
                headers=headers
            )
        except Exception:
            results["global"] = None
        # Fear & Greed Index (30-day history)
        try:
            results["fng"] = await self.fetch_json(
                "https://api.alternative.me/fng/?limit=30"
            )
        except Exception:
            results["fng"] = None
        # BTC Hash Rate
        try:
            results["hashrate"] = await self.fetch_json(
                "https://mempool.space/api/v1/mining/hashrate/pools/1m"
            )
        except Exception:
            results["hashrate"] = None
        return results

    async def parse(self, payload):
        if not payload:
            return []
        items = []
        now = datetime.now(UTC).isoformat()

        # Market data
        if payload.get("markets") and isinstance(payload["markets"], list):
            for coin in payload["markets"]:
                items.append(
                    self.std_signal(
                        id=f"cg-{coin.get('id', '')}",
                        title=f"{coin.get('name', '')} ({coin.get('symbol', '').upper()}): ${coin.get('current_price', 0):,.2f}",
                        summary=f"24h change: {coin.get('price_change_percentage_24h', 0):.2f}% | MCap: ${coin.get('market_cap', 0):,.0f}",
                        domain="economics",
                        severity=30,
                        india_score=5,
                        url=f"https://www.coingecko.com/en/coins/{coin.get('id', '')}",
                        published_at=now,
                        raw=coin,
                        tags=["crypto", "coingecko", "market"],
                    )
                )

        # Trending
        if payload.get("trending"):
            coins_list = payload["trending"].get("coins", []) or []
            if not isinstance(coins_list, list):
                coins_list = []
            for coin in coins_list[:10]:
                if not isinstance(coin, dict):
                    continue
                item = coin.get("item", coin)  # API may nest under "item" or not
                if not isinstance(item, dict):
                    continue
                items.append(
                    self.std_signal(
                        id=f"cg-trend-{item.get('coin_id', item.get('id', ''))}",
                        title=f"Trending: {item.get('name', '')} (rank #{item.get('market_cap_rank', '?')})",
                        summary=f"CoinGecko trending asset",
                        domain="economics",
                        severity=25,
                        india_score=5,
                        published_at=now,
                        raw=item,
                        tags=["crypto", "coingecko", "trending"],
                    )
                )

        # Fear & Greed
        if payload.get("fng"):
            fng_data = payload["fng"].get("data", [])
            if fng_data:
                latest = fng_data[0]
                value = int(latest.get("value", 50))
                classification = latest.get("value_classification", "Neutral")
                items.append(
                    self.std_signal(
                        id=f"fng-{latest.get('timestamp', '')}",
                        title=f"Crypto Fear & Greed: {value} ({classification})",
                        summary=f"30-day trend available. Current: {classification}",
                        domain="economics",
                        severity=40 if value < 20 or value > 80 else 25,
                        india_score=5,
                        published_at=now,
                        raw={"value": value, "classification": classification},
                        tags=["crypto", "sentiment", "fear_greed"],
                    )
                )

        # BTC Hash Rate
        if payload.get("hashrate"):
            hr = payload["hashrate"]
            hashrate_val = None
            if isinstance(hr, dict):
                hashrate_val = hr.get("currentHashrate")
                if not hashrate_val and isinstance(hr.get("hashrates"), list) and hr["hashrates"]:
                    hashrate_val = hr["hashrates"][0].get("avgHashrate")
            elif isinstance(hr, list) and hr:
                # mempool.space returns a list of hashrate entries
                first = hr[0] if isinstance(hr[0], dict) else {}
                hashrate_val = first.get("avgHashrate") or first.get("currentHashrate")
            if hashrate_val:
                items.append(
                    self.std_signal(
                        id=f"btc-hashrate-{now[:10]}",
                        title=f"BTC Hash Rate: {hashrate_val}",
                        summary="Bitcoin network mining hash rate from mempool.space",
                        domain="economics",
                        severity=20,
                        india_score=5,
                        published_at=now,
                        raw={"hashrate": hashrate_val},
                        tags=["crypto", "bitcoin", "hashrate"],
                    )
                )

        return items
